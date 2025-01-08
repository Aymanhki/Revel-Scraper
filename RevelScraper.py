from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException
)
import time
import re
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RevelScraper:
    def __init__(self, debug_port=9222):
        self.driver = None
        self.debug_port = debug_port
        self.previous_title = None
        self.module_number = 1

    def setup_chrome_driver(self):
        """Initialize Chrome WebDriver with remote debugging."""
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"localhost:{self.debug_port}")
            self.driver = webdriver.Chrome(options=options)
            logger.info("Chrome WebDriver initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Chrome WebDriver: {e}")
            raise

    def wait_and_find_element(self, by, value, timeout=10, retries=5, parent=None):
        """Wait for and find an element with retries."""
        for attempt in range(retries):
            try:
                if parent:
                    element = parent.find_element(by, value)
                else:
                    element = WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, value))
                    )
                return element
            except StaleElementReferenceException:
                if attempt == retries - 1:
                    raise
                logger.warning(f"Stale element, retry {attempt + 1}/{retries}")
                time.sleep(1)
            except TimeoutException:
                logger.error(f"Element not found: {value}")
                raise

    def extract_content(self):
        """Extract content from the current page with improved error handling."""
        page_data = []
        processed_sources = set()

        try:
            page_content = self.wait_and_find_element(By.CLASS_NAME, "page-content")
            elements = page_content.find_elements(
                By.XPATH,
                "./descendant::*[self::p or self::ul or self::ol or self::img or self::video or self::source or self::audio or self::iframe or self::embed or self::object]"
            )

            for element in elements:
                try:

                    if element.tag_name == "p":
                        paragraph_text = element.text.strip()
                        page_data.append(paragraph_text)

                    elif element.tag_name in ["ul", "ol"]:
                        list_title = self.get_list_title(element)

                        # check if the page data already has the list title within the last 3 or 5 lines, if so, then do not add the list title again and ensure that the list title already in the page data is preceeded by ### for markdown formatting
                        # Check if the list title already exists within the last 3–5 lines
                        duplicate_found = False
                        for recent_line in page_data[-5:]:
                            if list_title in recent_line:
                                duplicate_found = True
                                break

                        if duplicate_found:
                            for i, line in enumerate(page_data):
                                if list_title in line:
                                    page_data[i] = f"### {line}"
                                    break


                        list_items = []
                        for li in element.find_elements(By.TAG_NAME, "li"):
                            if li.text.strip():
                                list_items.append(f"- {li.text.strip()}")

                        if list_items:
                            if not duplicate_found:
                                page_data.append(f"### {list_title}")

                            page_data.extend(list_items)

                    elif element.tag_name in ["img", "video", "source", "audio", "iframe", "embed", "object"]:
                        for attr in ["src", "data-src", "href"]:
                            src = element.get_attribute(attr)
                            if src and src not in processed_sources:
                                processed_sources.add(src)
                                if element.tag_name == "img":
                                    page_data.append(f"<img src='{src}' style='max-width: 350px; display: block; margin: auto;'>")
                                else:
                                    media_type = element.tag_name.capitalize()
                                    page_data.append(f"\n- [{media_type}: {src}]({src})\n")
                                break

                except StaleElementReferenceException:
                    logger.warning(f"Stale element encountered while processing {element.tag_name}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing element {element.tag_name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error extracting content: {e}")

        return page_data

    def get_list_title(self, element, default="Listed Items"):
        """Get the title for a list with error handling."""
        try:
            prev_header = self.wait_and_find_element(
                By.XPATH,
                "./preceding::p[contains(@class, 'paragraphNumeroUno')][1]",
                timeout=5,
                parent=element  # Pass the list element as parent
            )

            if prev_header and len(prev_header.find_elements(By.XPATH, ".//*")) != 1:
                prev_header = self.wait_and_find_element(
                    By.XPATH,
                    "./preceding::*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6][1]",
                    timeout=5,
                    parent=element  # Pass the list element as parent
                )

            return prev_header.text.strip() if prev_header else default

        except (TimeoutException, StaleElementReferenceException):
            return default

    def get_active_page_title(self):
        """Get the title of the active page with error handling."""
        try:
            active_page = self.wait_and_find_element(
                By.XPATH,
                "//li[contains(@class, 'active-page')]"
            )
            return active_page.text.strip()
        except Exception as e:
            logger.warning(f"Failed to get page title: {e}")
            return "Unknown Module Title"

    def click_next_button(self):
        """Click the next button with error handling."""
        try:
            next_button = self.wait_and_find_element(
                By.XPATH,
                "//button[contains(@class, 'navigationBtn') and contains(@aria-label, 'next page')]"
            )
            next_button.click()
            time.sleep(1)  # Allow page to load
            return True
        except TimeoutException:
            logger.info("No more pages to navigate")
            return False
        except Exception as e:
            logger.error(f"Error clicking next button: {e}")
            return False

    def scrape_content(self):
        """Main method to scrape content from all pages."""
        try:
            self.setup_chrome_driver()

            with open("revel_content.md", "w", encoding="utf-8") as md_file:
                while True:
                    page_title = self.get_active_page_title()

                    if "Reading" not in page_title:
                        if not self.click_next_button():
                            break
                        continue

                    content = self.extract_content()

                    if content:
                        cleaned_title = self.clean_page_title(page_title)
                        self.write_content_to_file(md_file, cleaned_title, content)

                    if not self.click_next_button():
                        break

            logger.info("Content extraction completed successfully")

        except Exception as e:
            logger.error(f"Scraping failed: {e}")
        finally:
            if self.driver:
                self.driver.quit()

    @staticmethod
    def clean_page_title(title):
        """Clean the page title."""
        title = title.replace("Reading", "").strip()
        return re.sub(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d+', '', title).strip()

    def write_content_to_file(self, file, title, content):
        """Write content to the markdown file."""
        if title != self.previous_title:
            file.write(f"# Module {self.module_number}: {title}\n\n")
            self.module_number += 1
            self.previous_title = title

        file.write("\n\n".join(content))
        file.write("\n\n")
        file.flush()

if __name__ == "__main__":
    scraper = RevelScraper()
    scraper.scrape_content()