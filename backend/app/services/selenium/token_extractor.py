"""
Token Extractor for M365 APIs

After Selenium authenticates to M365 Admin Portal, this module extracts
access tokens from the browser session so we can make direct API calls.

This is MUCH faster than clicking through the UI for bulk operations.
"""

import json
import time
import logging
from typing import Optional, Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__name__)


class TokenExtractor:
    """Extract API tokens from authenticated Selenium browser session."""

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver

    def extract_graph_token(self) -> Optional[str]:
        """
        Extract Microsoft Graph API access token from browser.
        """
        try:
            # Method 1: Try to get from sessionStorage/localStorage
            logger.info("Trying storage extraction...")
            token = self._get_token_from_storage()
            if token:
                logger.info("Got Graph token from browser storage")
                return token

            # Method 2: Intercept from Users page API calls
            logger.info("Trying Users page API interception...")
            token = self._get_graph_token_via_users_api()
            if token:
                logger.info("Got Graph token via Users API interception")
                return token

            # Method 3: Use the portal's own API calls
            logger.info("Trying portal API interception...")
            token = self._get_token_via_portal_api()
            if token:
                logger.info("Got Graph token via portal API interception")
                return token

            # Method 4: Navigate to Graph Explorer
            logger.info("Trying Graph Explorer method...")
            token = self._get_token_via_graph_explorer()
            if token:
                logger.info("Got Graph token via Graph Explorer")
                return token

            logger.error("Could not extract Graph token with any method")
            return None

        except Exception as e:
            logger.error(f"Error extracting Graph token: {e}")
            return None

    def _get_token_from_storage(self) -> Optional[str]:
        """Try to extract token from browser storage - improved version."""
        try:
            # The M365 Admin Portal stores MSAL tokens with specific key patterns
            script = """
                function findGraphToken() {
                    // Check sessionStorage
                    for (let i = 0; i < sessionStorage.length; i++) {
                        let key = sessionStorage.key(i);
                        let value = sessionStorage.getItem(key);

                        // MSAL v2 stores tokens with keys containing 'accesstoken'
                        if (key.toLowerCase().includes('accesstoken')) {
                            try {
                                let parsed = JSON.parse(value);
                                // Look for Graph API audience
                                if (parsed.secret && (
                                    key.includes('graph.microsoft.com') ||
                                    key.includes('00000003-0000-0000-c000-000000000000')
                                )) {
                                    return parsed.secret;
                                }
                            } catch(e) {}
                        }
                    }

                    // Check localStorage too
                    for (let i = 0; i < localStorage.length; i++) {
                        let key = localStorage.key(i);
                        let value = localStorage.getItem(key);

                        if (key.toLowerCase().includes('accesstoken')) {
                            try {
                                let parsed = JSON.parse(value);
                                if (parsed.secret && (
                                    key.includes('graph.microsoft.com') ||
                                    key.includes('00000003-0000-0000-c000-000000000000')
                                )) {
                                    return parsed.secret;
                                }
                            } catch(e) {}
                        }
                    }

                    // Look for any JWT token that might be Graph
                    for (let storage of [sessionStorage, localStorage]) {
                        for (let i = 0; i < storage.length; i++) {
                            let key = storage.key(i);
                            let value = storage.getItem(key);

                            if (value && value.startsWith('eyJ')) {
                                // Decode JWT to check audience
                                try {
                                    let payload = JSON.parse(atob(value.split('.')[1]));
                                    if (payload.aud && (
                                        payload.aud.includes('graph.microsoft.com') ||
                                        payload.aud === 'https://graph.microsoft.com'
                                    )) {
                                        return value;
                                    }
                                } catch(e) {}
                            }

                            // Also check JSON values
                            try {
                                let parsed = JSON.parse(value);
                                if (parsed.secret && parsed.secret.startsWith('eyJ')) {
                                    let payload = JSON.parse(atob(parsed.secret.split('.')[1]));
                                    if (payload.aud && payload.aud.includes('graph')) {
                                        return parsed.secret;
                                    }
                                }
                            } catch(e) {}
                        }
                    }

                    return null;
                }
                return findGraphToken();
            """

            token = self.driver.execute_script(script)
            if token:
                return token

            return None

        except Exception as e:
            logger.debug(f"Storage extraction failed: {e}")
            return None

    def _get_graph_token_via_users_api(self) -> Optional[str]:
        """
        Navigate to Users page which definitely triggers Graph API calls.
        Intercept the authorization header.
        """
        try:
            original_url = self.driver.current_url

            # Navigate to Users page in M365 Admin
            self.driver.get("https://admin.microsoft.com/#/users")
            time.sleep(3)

            # Inject interceptor and trigger refresh
            script = """
                return new Promise((resolve) => {
                    window.__graphToken = null;

                    // Intercept XHR
                    const origOpen = XMLHttpRequest.prototype.open;
                    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

                    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                        if (name.toLowerCase() === 'authorization' && value.startsWith('Bearer ')) {
                            // Check if this is a Graph API call
                            if (this.__url && this.__url.includes('graph.microsoft.com')) {
                                window.__graphToken = value.replace('Bearer ', '');
                            }
                        }
                        return origSetHeader.apply(this, arguments);
                    };

                    XMLHttpRequest.prototype.open = function(method, url) {
                        this.__url = url;
                        return origOpen.apply(this, arguments);
                    };

                    // Also intercept fetch
                    const origFetch = window.fetch;
                    window.fetch = function(url, options) {
                        if (url && url.toString().includes('graph.microsoft.com')) {
                            if (options && options.headers) {
                                let auth = options.headers['Authorization'] || options.headers['authorization'];
                                if (auth && auth.startsWith('Bearer ')) {
                                    window.__graphToken = auth.replace('Bearer ', '');
                                }
                            }
                        }
                        return origFetch.apply(this, arguments);
                    };

                    // Wait for API calls to happen
                    setTimeout(() => {
                        resolve(window.__graphToken);
                    }, 5000);
                });
            """

            token = self.driver.execute_script(script)

            # Go back to original page
            self.driver.get(original_url)
            time.sleep(2)

            if token and token.startswith('eyJ'):
                return token

            return None

        except Exception as e:
            logger.debug(f"Users API interception failed: {e}")
            return None

    def get_graph_token_via_implicit_flow(self) -> Optional[str]:
        """
        Get Graph token by triggering an implicit auth flow.
        This opens a popup/redirect to get a token with Graph scopes.
        """
        try:
            # Microsoft's client ID for Graph Explorer (public client)
            client_id = "de8bc8b5-d9f9-48b1-a8ad-b748da725064"
            redirect_uri = "https://developer.microsoft.com/en-us/graph/graph-explorer"
            scopes = "User.ReadWrite.All Directory.ReadWrite.All"

            auth_url = (
                f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
                f"client_id={client_id}"
                f"&response_type=token"
                f"&redirect_uri={redirect_uri}"
                f"&scope={scopes}"
                f"&response_mode=fragment"
            )

            original_url = self.driver.current_url
            self.driver.get(auth_url)

            # Wait for redirect (should auto-auth since we're already logged in)
            time.sleep(5)

            # Check URL fragment for token
            current_url = self.driver.current_url
            if '#access_token=' in current_url:
                # Parse token from URL fragment
                fragment = current_url.split('#')[1]
                params = dict(x.split('=') for x in fragment.split('&'))
                token = params.get('access_token')

                # Go back
                self.driver.get(original_url)
                time.sleep(2)

                return token

            self.driver.get(original_url)
            return None

        except Exception as e:
            logger.debug(f"Implicit flow failed: {e}")
            return None

    def _get_token_via_graph_explorer(self) -> Optional[str]:
        """
        Navigate to Graph Explorer which will use existing session.
        This is a reliable way to get a token.
        """
        try:
            original_url = self.driver.current_url

            # Open Graph Explorer in same session
            self.driver.get("https://developer.microsoft.com/en-us/graph/graph-explorer")
            time.sleep(3)

            # Graph Explorer shows the access token in the UI when signed in
            # Look for the token in the page or network requests

            # Check if we can get token from the access token tab
            try:
                # Click on "Access token" tab if visible
                access_token_tab = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Access token')]"))
                )
                access_token_tab.click()
                time.sleep(1)

                # Get token from textarea or pre element
                token_element = self.driver.find_element(By.CSS_SELECTOR, "pre.token-value, textarea.token-value, code")
                token = token_element.text.strip()

                if token and token.startswith('eyJ'):
                    # Restore original URL
                    self.driver.get(original_url)
                    return token

            except Exception as e:
                logger.debug(f"Graph Explorer UI extraction failed: {e}")

            # Restore original URL
            self.driver.get(original_url)
            time.sleep(2)
            return None

        except Exception as e:
            logger.debug(f"Graph Explorer method failed: {e}")
            return None

    def _get_token_via_portal_api(self) -> Optional[str]:
        """
        Intercept token from the M365 Admin Portal's own API calls.
        The portal makes Graph API calls internally - we can capture those tokens.
        """
        try:
            # Navigate to a page that triggers Graph API calls
            self.driver.get("https://admin.microsoft.com/#/users")
            time.sleep(3)

            # Execute script to intercept fetch requests and extract auth headers
            script = """
                return new Promise((resolve) => {
                    // Store original fetch
                    const originalFetch = window.fetch;

                    // Override fetch to capture authorization header
                    window.fetch = function(...args) {
                        const [url, options] = args;
                        if (options && options.headers) {
                            const authHeader = options.headers['Authorization'] || options.headers['authorization'];
                            if (authHeader && authHeader.startsWith('Bearer ')) {
                                window.__capturedToken = authHeader.replace('Bearer ', '');
                            }
                        }
                        return originalFetch.apply(this, args);
                    };

                    // Trigger a refresh to capture token
                    setTimeout(() => {
                        resolve(window.__capturedToken || null);
                    }, 3000);
                });
            """

            token = self.driver.execute_script(script)
            if token and token.startswith('eyJ'):
                return token

            return None

        except Exception as e:
            logger.debug(f"Portal API interception failed: {e}")
            return None

    def extract_exchange_token(self) -> Optional[str]:
        """
        Extract Exchange Admin Center access token.

        The Exchange Admin Center uses a different token than Graph API.
        """
        try:
            original_url = self.driver.current_url

            # Navigate to Exchange Admin Center
            self.driver.get("https://admin.exchange.microsoft.com")
            time.sleep(5)

            # Exchange Admin uses its own token in sessionStorage
            script = """
                let tokens = [];
                for (let i = 0; i < sessionStorage.length; i++) {
                    let key = sessionStorage.key(i);
                    let value = sessionStorage.getItem(key);
                    if (value && value.includes('eyJ')) {
                        tokens.push({key: key, value: value});
                    }
                }

                // Also check for EXO-specific storage
                try {
                    let exoToken = sessionStorage.getItem('exchange_token') ||
                                   sessionStorage.getItem('ests.access_token') ||
                                   sessionStorage.getItem('EXO_TOKEN');
                    if (exoToken) {
                        tokens.push({key: 'exchange_direct', value: exoToken});
                    }
                } catch(e) {}

                return JSON.stringify(tokens);
            """

            result = self.driver.execute_script(script)

            if result:
                tokens = json.loads(result)
                for token_obj in tokens:
                    value = token_obj.get('value', '')
                    # Try to parse as JSON
                    try:
                        parsed = json.loads(value)
                        if 'secret' in parsed:
                            return parsed['secret']
                        if 'accessToken' in parsed:
                            return parsed['accessToken']
                    except:
                        # Check if it's a raw JWT
                        if value.startswith('eyJ'):
                            return value

            # If still no token, try to capture from network
            token = self._capture_exchange_token_from_network()

            # Restore original URL if needed
            if original_url != self.driver.current_url:
                self.driver.get(original_url)
                time.sleep(2)

            return token

        except Exception as e:
            logger.error(f"Error extracting Exchange token: {e}")
            return None

    def _capture_exchange_token_from_network(self) -> Optional[str]:
        """Capture Exchange token from network requests."""
        try:
            # Trigger an Exchange API call by navigating
            self.driver.get("https://admin.exchange.microsoft.com/#/mailboxes")
            time.sleep(3)

            # Similar interception technique
            script = """
                return new Promise((resolve) => {
                    const originalXHR = window.XMLHttpRequest;
                    const originalFetch = window.fetch;

                    // Capture from XHR
                    window.XMLHttpRequest = function() {
                        const xhr = new originalXHR();
                        const originalSetRequestHeader = xhr.setRequestHeader;
                        xhr.setRequestHeader = function(name, value) {
                            if (name.toLowerCase() === 'authorization' && value.startsWith('Bearer ')) {
                                window.__exchangeToken = value.replace('Bearer ', '');
                            }
                            return originalSetRequestHeader.apply(this, arguments);
                        };
                        return xhr;
                    };

                    // Capture from fetch
                    window.fetch = function(...args) {
                        const [url, options] = args;
                        if (options && options.headers) {
                            const auth = options.headers['Authorization'] || options.headers['authorization'];
                            if (auth && auth.startsWith('Bearer ')) {
                                window.__exchangeToken = auth.replace('Bearer ', '');
                            }
                        }
                        return originalFetch.apply(this, args);
                    };

                    setTimeout(() => {
                        resolve(window.__exchangeToken || null);
                    }, 5000);
                });
            """

            token = self.driver.execute_script(script)
            return token if token and token.startswith('eyJ') else None

        except Exception as e:
            logger.debug(f"Exchange network capture failed: {e}")
            return None

    def extract_all_tokens(self) -> Dict[str, Optional[str]]:
        """
        Extract all available tokens from the browser session.

        Returns dict with:
        - graph_token: For Graph API calls (users, licenses)
        - exchange_token: For Exchange Admin API calls (mailboxes)
        """
        logger.info("Extracting API tokens from browser session...")

        tokens = {
            "graph_token": self.extract_graph_token(),
            "exchange_token": self.extract_exchange_token(),
        }

        # Log what we got
        for name, token in tokens.items():
            if token:
                logger.info(f"✓ {name}: Extracted (length: {len(token)})")
            else:
                logger.warning(f"✗ {name}: Failed to extract")

        return tokens


def get_tokens_after_login(driver: webdriver.Chrome) -> Dict[str, Optional[str]]:
    """
    Convenience function to extract tokens after Selenium login.

    Usage:
        driver = webdriver.Chrome(options=opts)
        # ... login to M365 ...
        tokens = get_tokens_after_login(driver)
        graph_token = tokens['graph_token']
        exchange_token = tokens['exchange_token']
    """
    extractor = TokenExtractor(driver)
    return extractor.extract_all_tokens()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    """
    Test token extraction - requires manual login first.

    This test:
    1. Opens browser to M365 login
    2. Waits for you to login manually
    3. Extracts tokens
    4. Prints results
    """
    from selenium.webdriver.chrome.options import Options

    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("TOKEN EXTRACTION TEST")
    print("=" * 60)

    # Setup browser (visible for manual login)
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    # NOT headless - we need to login manually

    driver = webdriver.Chrome(options=opts)

    try:
        # Navigate to M365 Admin
        print("\n1. Opening M365 Admin Portal...")
        driver.get("https://admin.microsoft.com")

        print("\n2. Please login manually in the browser window.")
        print("   Press ENTER here when you're logged in and see the dashboard...\n")
        input("   >>> Press ENTER to continue...")

        print("\n3. Extracting tokens...")
        tokens = get_tokens_after_login(driver)

        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)

        for name, token in tokens.items():
            if token:
                print(f"\n✓ {name}:")
                print(f"  Length: {len(token)}")
                print(f"  Preview: {token[:50]}...")
            else:
                print(f"\n✗ {name}: NOT FOUND")

    finally:
        print("\n\nClosing browser in 5 seconds...")
        time.sleep(5)
        driver.quit()