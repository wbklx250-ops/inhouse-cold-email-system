"""
Instantly.ai Uploader Service
Automates uploading mailboxes to Instantly.ai via Selenium OAuth flow
"""
import asyncio
import logging
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox import Mailbox
from app.models.tenant import Tenant
from app.models.batch import SetupBatch
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


class InstantlyUploader:
    """Handles Selenium automation for uploading mailboxes to Instantly.ai"""
    
    def __init__(
        self,
        instantly_email: str,
        instantly_password: str,
        headless: bool = True,
        worker_id: int = 0
    ):
        self.instantly_email = instantly_email
        self.instantly_password = instantly_password
        self.headless = headless
        self.worker_id = worker_id
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        
    def setup_driver(self):
        """Initialize Chrome WebDriver with appropriate options"""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 30)
        logger.info(f"[Worker {self.worker_id}] Chrome driver initialized (headless={self.headless})")
        
    def random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0):
        """Add random delay to mimic human behavior"""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
        
    def login_to_instantly(self) -> bool:
        """
        Log in to Instantly.ai
        Returns True if successful, False otherwise
        """
        try:
            logger.info(f"[Worker {self.worker_id}] Navigating to Instantly.ai login...")
            self.driver.get("https://app.instantly.ai/app/login")
            self.random_delay(2, 4)
            
            # Wait for and fill email
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='email']"))
            )
            email_input.clear()
            email_input.send_keys(self.instantly_email)
            logger.info(f"[Worker {self.worker_id}] Email entered")
            self.random_delay(1, 2)
            
            # Fill password
            password_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
            password_input.clear()
            password_input.send_keys(self.instantly_password)
            logger.info(f"[Worker {self.worker_id}] Password entered")
            self.random_delay(1, 2)
            
            # Click login button
            login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            login_button.click()
            logger.info(f"[Worker {self.worker_id}] Login button clicked")
            
            # Wait for redirect to dashboard (URL should change)
            self.wait.until(lambda d: "login" not in d.current_url.lower())
            logger.info(f"[Worker {self.worker_id}] Successfully logged in to Instantly.ai")
            self.random_delay(2, 3)
            return True
            
        except Exception as e:
            logger.error(f"[Worker {self.worker_id}] Failed to login to Instantly: {str(e)}")
            return False
            
    def add_microsoft_account(
        self,
        email: str,
        password: str,
        mailbox_id: str
    ) -> Dict[str, Any]:
        """
        Add a Microsoft account to Instantly.ai via OAuth
        
        Args:
            email: Microsoft email address
            password: Microsoft password
            mailbox_id: Mailbox UUID for tracking
            
        Returns:
            Dict with 'success' (bool), 'error' (str or None)
        """
        try:
            logger.info(f"[Worker {self.worker_id}] Starting upload for {email} (ID: {mailbox_id})")
            
            # Navigate to accounts page
            self.driver.get("https://app.instantly.ai/app/accounts")
            self.random_delay(2, 3)
            
            # Click "Add Account" button
            try:
                add_button = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Add account') or contains(., 'Add Account')]"))
                )
                add_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Add Account' button")
                self.random_delay(1, 2)
            except TimeoutException:
                logger.error(f"[Worker {self.worker_id}] Could not find 'Add Account' button")
                return {"success": False, "error": "Could not find 'Add Account' button"}
            
            # Click Microsoft/Outlook option
            try:
                microsoft_button = self.wait.until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Microsoft') or contains(., 'Outlook')]"))
                )
                microsoft_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked Microsoft OAuth option")
                self.random_delay(2, 3)
            except TimeoutException:
                logger.error(f"[Worker {self.worker_id}] Could not find Microsoft OAuth button")
                return {"success": False, "error": "Could not find Microsoft OAuth button"}
            
            # Handle OAuth popup
            oauth_result = self._handle_oauth_flow(email, password)
            if not oauth_result["success"]:
                return oauth_result
            
            # Wait for confirmation that account was added
            try:
                self.wait.until(
                    EC.presence_of_element_located((By.XPATH, f"//td[contains(., '{email}')]"))
                )
                logger.info(f"[Worker {self.worker_id}] ✓ Successfully uploaded {email}")
                return {"success": True, "error": None}
            except TimeoutException:
                logger.warning(f"[Worker {self.worker_id}] Account may have been added but confirmation not found")
                return {"success": True, "error": None}
                
        except Exception as e:
            error_msg = f"Unexpected error during upload: {str(e)}"
            logger.error(f"[Worker {self.worker_id}] {error_msg}")
            return {"success": False, "error": error_msg}
            
    def _handle_oauth_flow(self, email: str, password: str) -> Dict[str, Any]:
        """
        Handle Microsoft OAuth popup flow
        
        Args:
            email: Microsoft email
            password: Microsoft password
            
        Returns:
            Dict with 'success' (bool), 'error' (str or None)
        """
        try:
            # Store original window handle
            original_window = self.driver.current_window_handle
            
            # Wait for OAuth popup window
            self.wait.until(lambda d: len(d.window_handles) > 1)
            all_windows = self.driver.window_handles
            popup_window = [w for w in all_windows if w != original_window][0]
            
            # Switch to popup
            self.driver.switch_to.window(popup_window)
            logger.info(f"[Worker {self.worker_id}] Switched to OAuth popup")
            self.random_delay(2, 3)
            
            # Enter email
            try:
                email_input = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='email'], input[name='loginfmt']"))
                )
                email_input.clear()
                email_input.send_keys(email)
                logger.info(f"[Worker {self.worker_id}] Entered email in OAuth popup")
                self.random_delay(1, 2)
                
                # Click Next
                next_button = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
                next_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Next' after email")
                self.random_delay(2, 3)
            except TimeoutException:
                logger.error(f"[Worker {self.worker_id}] Could not find email input in OAuth popup")
                self.driver.switch_to.window(original_window)
                return {"success": False, "error": "Could not find email input in OAuth popup"}
            
            # Enter password
            try:
                password_input = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password'], input[name='passwd']"))
                )
                password_input.clear()
                password_input.send_keys(password)
                logger.info(f"[Worker {self.worker_id}] Entered password in OAuth popup")
                self.random_delay(1, 2)
                
                # Click Sign In
                signin_button = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
                signin_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Sign In'")
                self.random_delay(3, 5)
            except TimeoutException:
                logger.error(f"[Worker {self.worker_id}] Could not find password input in OAuth popup")
                self.driver.switch_to.window(original_window)
                return {"success": False, "error": "Could not find password input in OAuth popup"}
            
            # Handle "Stay signed in?" prompt (if appears)
            try:
                stay_signed_in = self.driver.find_element(By.CSS_SELECTOR, "input[type='submit'][value='Yes']")
                stay_signed_in.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Yes' on 'Stay signed in'")
                self.random_delay(2, 3)
            except:
                logger.info(f"[Worker {self.worker_id}] No 'Stay signed in' prompt found (OK)")
            
            # Handle permissions consent (if appears)
            try:
                accept_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit'][value='Accept'], button[id='accept-button']"))
                )
                accept_button.click()
                logger.info(f"[Worker {self.worker_id}] Clicked 'Accept' on permissions")
                self.random_delay(2, 3)
            except TimeoutException:
                logger.info(f"[Worker {self.worker_id}] No consent prompt found (may have been pre-consented)")
            
            # Wait for popup to close (OAuth complete)
            WebDriverWait(self.driver, 20).until(lambda d: len(d.window_handles) == 1)
            logger.info(f"[Worker {self.worker_id}] OAuth popup closed - flow complete")
            
            # Switch back to original window
            self.driver.switch_to.window(original_window)
            self.random_delay(2, 3)
            
            return {"success": True, "error": None}
            
        except Exception as e:
            error_msg = f"OAuth flow error: {str(e)}"
            logger.error(f"[Worker {self.worker_id}] {error_msg}")
            # Try to switch back to original window
            try:
                if self.driver.current_window_handle != original_window:
                    self.driver.switch_to.window(original_window)
            except:
                pass
            return {"success": False, "error": error_msg}
            
    def cleanup(self):
        """Clean up WebDriver resources"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info(f"[Worker {self.worker_id}] Chrome driver closed")
            except Exception as e:
                logger.error(f"[Worker {self.worker_id}] Error closing driver: {str(e)}")


def process_mailbox_sync(
    uploader: InstantlyUploader,
    mailbox_data: Dict[str, Any],
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Synchronous function to process a single mailbox upload
    Runs in ThreadPoolExecutor
    
    Args:
        uploader: InstantlyUploader instance
        mailbox_data: Dict with 'id', 'email', 'password'
        max_retries: Maximum retry attempts
        
    Returns:
        Dict with 'mailbox_id', 'success', 'error', 'retries'
    """
    mailbox_id = mailbox_data["id"]
    email = mailbox_data["email"]
    password = mailbox_data["password"]
    
    for attempt in range(max_retries + 1):
        try:
            result = uploader.add_microsoft_account(email, password, mailbox_id)
            if result["success"]:
                return {
                    "mailbox_id": mailbox_id,
                    "success": True,
                    "error": None,
                    "retries": attempt
                }
            else:
                if attempt < max_retries:
                    logger.warning(f"[Worker {uploader.worker_id}] Attempt {attempt + 1} failed for {email}, retrying...")
                    time.sleep(3)
                else:
                    logger.error(f"[Worker {uploader.worker_id}] All {max_retries + 1} attempts failed for {email}")
                    return {
                        "mailbox_id": mailbox_id,
                        "success": False,
                        "error": result["error"],
                        "retries": attempt
                    }
        except Exception as e:
            error_msg = f"Exception during upload: {str(e)}"
            logger.error(f"[Worker {uploader.worker_id}] {error_msg}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                return {
                    "mailbox_id": mailbox_id,
                    "success": False,
                    "error": error_msg,
                    "retries": attempt
                }


async def run_instantly_upload_for_batch(
    batch_id: str,
    instantly_email: str,
    instantly_password: str,
    num_workers: int = 3,
    headless: bool = True,
    skip_uploaded: bool = True
) -> Dict[str, Any]:
    """
    Main async function to upload all mailboxes in a batch to Instantly.ai
    Uses parallel browser workers for faster processing
    
    Args:
        batch_id: SetupBatch UUID
        instantly_email: Instantly.ai account email
        instantly_password: Instantly.ai account password
        num_workers: Number of parallel browser workers (1-5)
        headless: Run browsers in headless mode
        skip_uploaded: Skip mailboxes already uploaded
        
    Returns:
        Dict with summary: total, uploaded, failed, skipped, errors
    """
    logger.info(f"Starting Instantly upload for batch {batch_id} with {num_workers} workers")
    
    # Fetch mailboxes from database
    async with async_session_factory() as session:
        # Get batch to verify it exists
        batch_result = await session.execute(
            select(SetupBatch).where(SetupBatch.id == batch_id)
        )
        batch = batch_result.scalar_one_or_none()
        if not batch:
            return {"error": "Batch not found", "total": 0, "uploaded": 0, "failed": 0, "skipped": 0}
        
        # Get all mailboxes for tenants in this batch
        query = (
            select(Mailbox)
            .join(Tenant, Mailbox.tenant_id == Tenant.id)
            .where(Tenant.batch_id == batch_id)
        )
        
        if skip_uploaded:
            query = query.where(Mailbox.instantly_uploaded == False)
            
        result = await session.execute(query)
        mailboxes = result.scalars().all()
        
        if not mailboxes:
            logger.info(f"No mailboxes to upload for batch {batch_id}")
            return {"total": 0, "uploaded": 0, "failed": 0, "skipped": 0, "errors": []}
        
        # Prepare mailbox data for workers
        mailbox_list = [
            {
                "id": str(mb.id),
                "email": mb.email,
                "password": mb.initial_password or ""
            }
            for mb in mailboxes
        ]
    
    logger.info(f"Found {len(mailbox_list)} mailboxes to upload")
    
    # Run parallel upload using ThreadPoolExecutor
    uploaded_count = 0
    failed_count = 0
    errors = []
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Create one uploader per worker
        uploaders = []
        for i in range(num_workers):
            uploader = InstantlyUploader(
                instantly_email=instantly_email,
                instantly_password=instantly_password,
                headless=headless,
                worker_id=i
            )
            uploader.setup_driver()
            
            # Login to Instantly
            if not uploader.login_to_instantly():
                logger.error(f"Worker {i} failed to login, skipping")
                uploader.cleanup()
                continue
                
            uploaders.append(uploader)
        
        if not uploaders:
            return {
                "error": "All workers failed to login to Instantly",
                "total": len(mailbox_list),
                "uploaded": 0,
                "failed": len(mailbox_list),
                "skipped": 0,
                "errors": ["All workers failed to login"]
            }
        
        try:
            # Submit tasks to executor
            futures = []
            for i, mailbox_data in enumerate(mailbox_list):
                uploader = uploaders[i % len(uploaders)]
                future = executor.submit(process_mailbox_sync, uploader, mailbox_data)
                futures.append(future)
            
            # Process results as they complete
            for future in as_completed(futures):
                result = future.result()
                
                # Update database
                async with async_session_factory() as session:
                    if result["success"]:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                instantly_uploaded=True,
                                instantly_uploaded_at=datetime.utcnow(),
                                instantly_upload_error=None
                            )
                        )
                        uploaded_count += 1
                    else:
                        await session.execute(
                            update(Mailbox)
                            .where(Mailbox.id == result["mailbox_id"])
                            .values(
                                instantly_uploaded=False,
                                instantly_upload_error=result["error"]
                            )
                        )
                        failed_count += 1
                        errors.append(result["error"])
                    
                    await session.commit()
                
                logger.info(f"Progress: {uploaded_count + failed_count}/{len(mailbox_list)} processed")
        
        finally:
            # Cleanup all uploaders
            for uploader in uploaders:
                uploader.cleanup()
    
    logger.info(f"Instantly upload complete: {uploaded_count} uploaded, {failed_count} failed")
    
    return {
        "total": len(mailbox_list),
        "uploaded": uploaded_count,
        "failed": failed_count,
        "skipped": 0,
        "errors": errors[:10]  # Limit to first 10 errors
    }
