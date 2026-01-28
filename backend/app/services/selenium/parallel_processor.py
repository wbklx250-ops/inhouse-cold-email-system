"""
Parallel Domain Processor - Process multiple domains simultaneously with DNS propagation waits.

Architecture:
1. Start domain setup, add DNS records to Cloudflare
2. After adding records, put domain in a "waiting" queue
3. Start next domain while previous one propagates
4. Check waiting domains every 2 minutes
5. Run up to 3 browsers simultaneously
"""

import asyncio
import logging
import time
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty

logger = logging.getLogger(__name__)

# Configuration
MAX_BROWSERS = 2  # Reduced from 3 for Railway to give each browser more resources
DNS_CHECK_INTERVAL = 120  # 2 minutes
MAX_DNS_WAIT_TIME = 1200  # 20 minutes (10 attempts x 2 minutes)
MAX_RETRY_ATTEMPTS = 10


class DomainState(Enum):
    """Domain processing states."""
    PENDING = "pending"           # Not started
    ADDING_DOMAIN = "adding"      # Adding domain to M365
    ADDING_DNS = "adding_dns"     # Adding DNS records to Cloudflare
    WAITING_DNS = "waiting_dns"   # Waiting for DNS propagation
    VERIFYING = "verifying"       # Attempting to verify in M365
    COMPLETED = "completed"       # Successfully completed
    FAILED = "failed"             # Failed after all retries


@dataclass
class DomainTask:
    """Represents a domain being processed."""
    tenant_id: UUID
    domain_id: UUID
    domain_name: str
    admin_email: str
    admin_password: str
    totp_secret: str
    cloudflare_zone_id: str
    
    # State tracking
    state: DomainState = DomainState.PENDING
    dns_added_at: Optional[datetime] = None
    retry_count: int = 0
    last_check_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict] = None
    
    # Progress tracking
    txt_value: Optional[str] = None
    domain_added: bool = False
    domain_verified: bool = False
    dns_configured: bool = False
    dkim_enabled: bool = False


@dataclass
class ProcessorStats:
    """Statistics for the processor."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    in_progress: int = 0
    waiting_dns: int = 0
    start_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        elapsed = ""
        if self.start_time:
            elapsed = str(datetime.utcnow() - self.start_time).split('.')[0]
        return {
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "in_progress": self.in_progress,
            "waiting_dns": self.waiting_dns,
            "elapsed": elapsed
        }


class ParallelDomainProcessor:
    """
    Processes multiple domains in parallel while managing DNS propagation waits.
    
    Key features:
    - Max 3 browsers running simultaneously
    - Domains waiting for DNS don't block others
    - Automatic retry every 2 minutes for waiting domains
    - Max 20 minutes wait time per domain
    """
    
    def __init__(
        self,
        on_progress: Optional[Callable[[str, str, str], None]] = None,
        on_complete: Optional[Callable[[str, bool, Dict], None]] = None
    ):
        self.on_progress = on_progress  # (domain_name, state, message)
        self.on_complete = on_complete  # (domain_name, success, result)
        
        self.pending_queue: Queue[DomainTask] = Queue()
        self.waiting_queue: List[DomainTask] = []  # Domains waiting for DNS
        self.active_tasks: Dict[str, DomainTask] = {}  # domain_name -> task
        self.completed_tasks: List[DomainTask] = []
        
        self.stats = ProcessorStats()
        self.running = False
        self.lock = threading.Lock()
        
        # Import here to avoid circular imports
        from app.services.selenium.admin_portal import setup_domain_complete_via_admin_portal
        from app.services.cloudflare_sync import add_txt, add_mx, add_spf, add_cname
        
        self.setup_domain = setup_domain_complete_via_admin_portal
    
    def _report_progress(self, domain_name: str, state: str, message: str):
        """Report progress to callback."""
        logger.info(f"[{domain_name}] {state}: {message}")
        if self.on_progress:
            try:
                self.on_progress(domain_name, state, message)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")
    
    def _report_complete(self, task: DomainTask, success: bool):
        """Report completion to callback."""
        result = {
            "tenant_id": str(task.tenant_id),
            "domain_name": task.domain_name,
            "success": success,
            "domain_added": task.domain_added,
            "domain_verified": task.domain_verified,
            "dns_configured": task.dns_configured,
            "dkim_enabled": task.dkim_enabled,
            "error": task.error,
            "retry_count": task.retry_count
        }
        
        if self.on_complete:
            try:
                self.on_complete(task.domain_name, success, result)
            except Exception as e:
                logger.error(f"Complete callback error: {e}")
        
        return result
    
    async def add_domain(self, task: DomainTask):
        """Add a domain to the processing queue."""
        self.pending_queue.put(task)
        with self.lock:
            self.stats.total += 1
        logger.info(f"[{task.domain_name}] Added to queue (total: {self.stats.total})")
    
    async def process_domain_initial(self, task: DomainTask) -> bool:
        """
        Phase 1: Add domain to M365 and DNS records to Cloudflare.
        
        Returns True if domain should move to waiting queue.
        Returns False if domain is complete or failed.
        """
        self._report_progress(task.domain_name, "starting", "Beginning domain setup")
        
        try:
            # Run the Selenium automation
            result = self.setup_domain(
                domain=task.domain_name,
                zone_id=task.cloudflare_zone_id,
                admin_email=task.admin_email,
                admin_password=task.admin_password,
                totp_secret=task.totp_secret,
                headless=True
            )
            
            # Check result
            if result.get("success"):
                # Domain fully completed (rare on first try)
                task.state = DomainState.COMPLETED
                task.domain_added = True
                task.domain_verified = result.get("verified", False)
                task.dns_configured = result.get("dns_configured", False)
                self._report_progress(task.domain_name, "completed", "Domain setup complete!")
                return False
            
            elif result.get("dns_configured"):
                # DNS added, waiting for propagation
                task.state = DomainState.WAITING_DNS
                task.domain_added = True
                task.dns_configured = True
                task.dns_added_at = datetime.utcnow()
                self._report_progress(task.domain_name, "waiting", "DNS added, waiting for propagation...")
                return True  # Move to waiting queue
            
            else:
                # Failed
                task.state = DomainState.FAILED
                task.error = result.get("error", "Unknown error")
                self._report_progress(task.domain_name, "failed", f"Error: {task.error}")
                return False
                
        except Exception as e:
            logger.exception(f"[{task.domain_name}] Exception during initial setup")
            task.state = DomainState.FAILED
            task.error = str(e)
            self._report_progress(task.domain_name, "failed", f"Exception: {e}")
            return False
    
    async def retry_dns_verification(self, task: DomainTask) -> bool:
        """
        Phase 2: Retry DNS verification for a waiting domain.
        
        Returns True if still waiting, False if complete or failed.
        """
        task.retry_count += 1
        task.last_check_at = datetime.utcnow()
        
        self._report_progress(
            task.domain_name, 
            "retrying", 
            f"Retry {task.retry_count}/{MAX_RETRY_ATTEMPTS} - checking DNS propagation"
        )
        
        try:
            # Re-run setup - it will detect DNS is already added and try to verify
            result = self.setup_domain(
                domain=task.domain_name,
                zone_id=task.cloudflare_zone_id,
                admin_email=task.admin_email,
                admin_password=task.admin_password,
                totp_secret=task.totp_secret,
                headless=True
            )
            
            if result.get("success"):
                task.state = DomainState.COMPLETED
                task.domain_verified = True
                task.dkim_enabled = result.get("dkim_enabled", False)
                self._report_progress(task.domain_name, "completed", "Domain verification successful!")
                return False
            
            elif task.retry_count >= MAX_RETRY_ATTEMPTS:
                # Max retries reached
                task.state = DomainState.FAILED
                task.error = f"DNS verification failed after {MAX_RETRY_ATTEMPTS} attempts (20 minutes)"
                self._report_progress(task.domain_name, "failed", task.error)
                return False
            
            else:
                # Still waiting
                self._report_progress(
                    task.domain_name, 
                    "waiting", 
                    f"Still waiting for DNS propagation (attempt {task.retry_count}/{MAX_RETRY_ATTEMPTS})"
                )
                return True
                
        except Exception as e:
            logger.exception(f"[{task.domain_name}] Exception during retry")
            if task.retry_count >= MAX_RETRY_ATTEMPTS:
                task.state = DomainState.FAILED
                task.error = f"Exception after {MAX_RETRY_ATTEMPTS} attempts: {e}"
                return False
            return True  # Keep trying
    
    async def process_all(self, tasks: List[DomainTask]) -> Dict:
        """
        Process all domains with parallel execution and DNS wait management.
        
        Args:
            tasks: List of DomainTask objects to process
            
        Returns:
            Summary dict with results
        """
        self.stats = ProcessorStats(total=len(tasks), start_time=datetime.utcnow())
        self.running = True
        
        # Add all tasks to pending queue
        for task in tasks:
            self.pending_queue.put(task)
        
        logger.info("=" * 60)
        logger.info(f"=== PARALLEL PROCESSOR: {len(tasks)} domains, max {MAX_BROWSERS} browsers ===")
        logger.info("=" * 60)
        
        results = []
        
        while self.running:
            # Check if we're done
            with self.lock:
                all_done = (
                    self.pending_queue.empty() and
                    len(self.active_tasks) == 0 and
                    len(self.waiting_queue) == 0
                )
            
            if all_done:
                break
            
            # Start new tasks if we have capacity
            while len(self.active_tasks) < MAX_BROWSERS:
                try:
                    task = self.pending_queue.get_nowait()
                    self.active_tasks[task.domain_name] = task
                    self.stats.in_progress += 1
                    
                    # Process initial setup
                    should_wait = await self.process_domain_initial(task)
                    
                    # Remove from active
                    del self.active_tasks[task.domain_name]
                    self.stats.in_progress -= 1
                    
                    if should_wait:
                        # Move to waiting queue
                        self.waiting_queue.append(task)
                        self.stats.waiting_dns += 1
                    else:
                        # Complete or failed
                        self.completed_tasks.append(task)
                        if task.state == DomainState.COMPLETED:
                            self.stats.completed += 1
                        else:
                            self.stats.failed += 1
                        results.append(self._report_complete(task, task.state == DomainState.COMPLETED))
                        
                except Empty:
                    break  # No more pending tasks
            
            # Check waiting tasks for DNS propagation
            now = datetime.utcnow()
            tasks_to_remove = []
            
            for task in self.waiting_queue:
                # Check if 2 minutes have passed since last check
                last_check = task.last_check_at or task.dns_added_at
                if last_check and (now - last_check).total_seconds() >= DNS_CHECK_INTERVAL:
                    # Only retry if we have browser capacity
                    if len(self.active_tasks) < MAX_BROWSERS:
                        self.active_tasks[task.domain_name] = task
                        self.stats.in_progress += 1
                        
                        still_waiting = await self.retry_dns_verification(task)
                        
                        del self.active_tasks[task.domain_name]
                        self.stats.in_progress -= 1
                        
                        if not still_waiting:
                            tasks_to_remove.append(task)
                            self.stats.waiting_dns -= 1
                            self.completed_tasks.append(task)
                            if task.state == DomainState.COMPLETED:
                                self.stats.completed += 1
                            else:
                                self.stats.failed += 1
                            results.append(self._report_complete(task, task.state == DomainState.COMPLETED))
            
            # Remove completed/failed from waiting queue
            for task in tasks_to_remove:
                self.waiting_queue.remove(task)
            
            # Brief pause before next iteration
            await asyncio.sleep(5)
        
        self.running = False
        
        # Final summary
        logger.info("=" * 60)
        logger.info(f"=== PARALLEL PROCESSOR COMPLETE ===")
        logger.info(f"  Total: {self.stats.total}")
        logger.info(f"  Completed: {self.stats.completed}")
        logger.info(f"  Failed: {self.stats.failed}")
        logger.info(f"  Elapsed: {datetime.utcnow() - self.stats.start_time}")
        logger.info("=" * 60)
        
        return {
            "total": self.stats.total,
            "successful": self.stats.completed,
            "failed": self.stats.failed,
            "results": results
        }
    
    def stop(self):
        """Stop processing."""
        self.running = False
        logger.info("Parallel processor stop requested")


async def run_parallel_step5(
    tenants_data: List[Dict],
    on_progress: Optional[Callable] = None,
    on_complete: Optional[Callable] = None
) -> Dict:
    """
    Run Step 5 for multiple tenants in parallel.
    
    Args:
        tenants_data: List of dicts with tenant/domain info:
            - tenant_id: UUID
            - domain_id: UUID
            - domain_name: str
            - admin_email: str
            - admin_password: str
            - totp_secret: str
            - cloudflare_zone_id: str
        on_progress: Optional callback (domain_name, state, message)
        on_complete: Optional callback (domain_name, success, result)
    
    Returns:
        Summary dict with results
    """
    processor = ParallelDomainProcessor(on_progress, on_complete)
    
    # Create tasks
    tasks = []
    for data in tenants_data:
        task = DomainTask(
            tenant_id=data["tenant_id"],
            domain_id=data["domain_id"],
            domain_name=data["domain_name"],
            admin_email=data["admin_email"],
            admin_password=data["admin_password"],
            totp_secret=data["totp_secret"],
            cloudflare_zone_id=data["cloudflare_zone_id"]
        )
        tasks.append(task)
    
    return await processor.process_all(tasks)
