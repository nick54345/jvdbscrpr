import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from googletrans import Translator

# --- Configuration ---
JAVDB_VR_BASE_URL = "https://javdb.com/search?f=download&q=VR&sb=1" # Base URL without page number
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
if not DISCORD_WEBHOOK_URL:
    print("Error: DISCORD_WEBHOOK_URL environment variable not set. Please set it as a GitHub Secret.")
    exit(1) # Corrected: Added newline after exit(1)
PROCESSED_TITLES_FILE = "processed_vr_titles.txt" # File to store already processed titles
REQUEST_DELAY_SECONDS = 1.5 # Delay in seconds between fetching detail pages (javdb.com or jav321.com)
LISTING_PAGE_DELAY_SECONDS = 2 # Delay in seconds between fetching consecutive listing pages from javdb.com
NUMBER_OF_PAGES_TO_SCRAPE = 3 # Number of listing pages to scrape from javdb.com

# Initialize the Translator
translator = Translator()

# --- Global Session for Web Requests ---
# This helps maintain cookies across requests and often makes requests look more "human"
session = requests.Session()
# Update User-Agent with a more recent Firefox version for better evasion
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0", # Updated User-Agent
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
})

# --- Function to load processed titles ---
def load_processed_titles(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f)
    return set()

# --- Function to save processed titles ---
def save_processed_titles(filename, titles):
    with open(filename, 'w', encoding='utf-8') as f:
        for title in sorted(list(titles)):
            f.write(f"{title}\n")

# --- Function to translate text ---
def translate_text(text, dest_lang='en'):
    try:
        # Attempt to detect source language for better translation, then translate
        translated = translator.translate(text, dest=dest_lang)
        if translated and translated.text:
            return translated.text
        return text # Return original if translation fails or is empty
    except Exception as e:
        print(f"Translation failed for text: '{text[:50]}...' Error: {e}")
        return text # Return original text on error

# --- Function to get rating from jav321.com ---
def get_jav321_rating(product_id):
    if not product_id:
        return None

    # Construct the jav321.com URL
    jav321_url = f"https://jav321.com/video/{product_id.lower()}"
    print(f"    Checking jav321.com for rating: {jav321_url}")
    time.sleep(REQUEST_DELAY_SECONDS) # Be polite to jav321.com too

    try:
        response = session.get(jav321_url) # Changed to use global session
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Search for the <b> tag that contains "Average Rating"
        # The rating value is in the next sibling <font> tag
        rating_label_tag = None
        for b_tag in soup.find_all('b'):
            if "Average Rating" in b_tag.get_text():
                rating_label_tag = b_tag
                break

        if rating_label_tag:
            # The rating value " : 5" is in the next sibling <font> tag
            rating_value_font_tag = rating_label_tag.find_next_sibling('font')
            if rating_value_font_tag:
                full_text = rating_value_font_tag.get_text(strip=True)
                # Extract just the number (e.g., "5" from ": 5" or "5.0")
                match = re.search(r'(\d+(\.\d+)?)', full_text)
                if match:
                    rating = match.group(1)
                    return rating
        return None # Return None if rating element not found
    except requests.exceptions.RequestException as e:
        print(f"    Error accessing jav321.com for {product_id}: {e}")
        return None
    except Exception as e:
        print(f"    An unexpected error occurred while parsing jav321.com for {product_id}: {e}")
        return None


# --- Function to send message to Discord ---
def send_discord_message(title, url, image_url=None, tags=None, rating=None):
    embed_fields = [
        {
            "name": "Title",
            "value": f"[{title}]({url})" # Make the title a clickable link
        }
    ]
    
    # Add rating field if available, typically after the title
    if rating:
        embed_fields.append({
            "name": "Rating (jav321.com)",
            "value": f"⭐ {rating}",
            "inline": True # Display on the same line if space allows
        })

    embed_fields.append({
        "name": "Source",
        "value": f"[View on JavDB]({url})"
    })

    # Add tags field if tags are available
    if tags:
        display_tags = sorted(list(set(tags))) # Ensure uniqueness and sort
        embed_fields.append({
            "name": "Tags",
            "value": ", ".join(display_tags),
            "inline": False # Set to False for better display if many tags
        })

    image_display_field = {"url": image_url} if image_url else None

    payload = {
        "content": "New VR Title Alert!",
        "embeds": [
            {
                "title": "",
                "url": "",
                "description": "A new VR title has been released on your site.",
                "color": 65280, # Green color for Discord embed (decimal for #00FF00)
                "fields": embed_fields,
                "image": image_display_field
            }
        ]
    }
    headers = {"Content-Type": "application/json"} # Headers for Discord API are different
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, data=json.dumps(payload), headers=headers)
        response.raise_for_status()
        print(f"Sent notification for: {title}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending Discord message for {title}: {e}")

# --- Main scraping and notification logic ---
def scrape_new_vr_titles():
    print(f"Starting VR title scraping for {NUMBER_OF_PAGES_TO_SCRAPE} pages from {JAVDB_VR_BASE_URL}...")
    processed_titles = load_processed_titles(PROCESSED_TITLES_FILE)
    newly_processed_titles = set(processed_titles)

    found_any_new_titles = False

    for page_num in range(1, NUMBER_OF_PAGES_TO_SCRAPE + 1):
        page_url = f"{JAVDB_VR_BASE_URL}&page={page_num}"
        print(f"\n--- Scraping page {page_num}: {page_url} ---")

        try:
            response = session.get(page_url) # Changed to use global session
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            video_items = soup.find_all('div', class_='item')

            if not video_items:
                print(f"No video items found on page {page_num}. Ending search early.")
                break

            found_new_on_page = False
            for item in video_items:
                link_tag = item.find('a', class_='box')
                if not link_tag:
                    continue

                title_tag = link_tag.find('div', class_='video-title')
                original_title = title_tag.text.strip() if title_tag else "No Title Found"
                
                # --- Extract Product ID ---
                # This regex looks for an alphanumeric string with hyphens at the beginning of the title
                product_id_match = re.match(r'([A-Z0-9-]+)', original_title)
                product_id = product_id_match.group(1) if product_id_match else None

                translated_title = translate_text(original_title)
                display_title = translated_title if translated_title != original_title else original_title

                relative_url = link_tag.get('href')
                if not relative_url:
                    continue
                full_url = requests.compat.urljoin(JAVDB_VR_BASE_URL, relative_url)

                image_tag = item.find('img', loading='lazy')
                image_url = image_tag.get('src') if image_tag else None

                if original_title not in processed_titles:
                    print(f"    Found new VR title on page {page_num}: {original_title}. Fetching additional details...")
                    found_new_on_page = True
                    found_any_new_titles = True

                    extracted_tags = set()
                    tags_div = item.find('div', class_='tags has-addons')
                    if tags_div:
                        for tag_span in tags_div.find_all('span', class_='tag'):
                            tag_text = tag_span.text.strip()
                            if tag_text:
                                extracted_tags.add(tag_text)

                    if title_tag:
                        title_text = original_title
                        if re.search(r'【VR】|\[VR\]', title_text, re.IGNORECASE):
                            extracted_tags.add("VR")

                    # --- Get Rating from jav321.com ---
                    rating = None
                    if product_id:
                        rating = get_jav321_rating(product_id)
                    else:
                        print(f"    No product ID found for '{original_title}', skipping jav321.com rating check.")

                    # --- Get Tags from javdb.com detail page ---
                    print(f"    Visiting javdb.com detail page: {full_url}")
                    time.sleep(REQUEST_DELAY_SECONDS)

                    try:
                        detail_response = session.get(full_url) # Changed to use global session
                        detail_response.raise_for_status()
                        detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

                        tags_panel_block = None
                        for panel_block_div in detail_soup.find_all('div', class_='panel-block'):
                            if panel_block_div.find('strong', string='Tags:'):
                                tags_panel_block = panel_block_div
                                break

                        if tags_panel_block:
                            tags_value_span = tags_panel_block.find('span', class_='value')
                            if tags_value_span:
                                for tag_link in tags_value_span.find_all('a'):
                                    tag_text = tag_link.text.strip()
                                    if tag_text:
                                        extracted_tags.add(tag_text)

                    except requests.exceptions.RequestException as detail_e:
                        print(f"    Error accessing javdb.com detail page {full_url}: {detail_e}")
                        print("    Proceeding with tags found from listing page only.")
                    except Exception as detail_e:
                        print(f"    An unexpected error occurred while parsing javdb.com detail page {full_url}: {detail_e}")
                        print("    Proceeding with tags found from listing page only.")

                    send_discord_message(display_title, full_url, image_url, list(extracted_tags), rating)
                    newly_processed_titles.add(original_title)

            if not found_new_on_page and page_num == 1:
                    print("    No new titles found on this page.")
            
            if page_num < NUMBER_OF_PAGES_TO_SCRAPE:
                print(f"    Finished scraping page {page_num}. Waiting {LISTING_PAGE_DELAY_SECONDS} seconds before next page...")
                time.sleep(LISTING_PAGE_DELAY_SECONDS)

        except requests.exceptions.RequestException as e:
            print(f"Error accessing page {page_num} ({page_url}): {e}. Skipping to next page.")
        except Exception as e:
            print(f"An unexpected error occurred while scraping page {page_num}: {e}. Skipping to next page.")

    if not found_any_new_titles:
        print("\nNo new VR titles found across all pages on this run.")
    else:
        print("\nSuccessfully sent notifications for all new titles found.")

    save_processed_titles(PROCESSED_TITLES_FILE, newly_processed_titles)
    print("Scraping finished. Processed titles saved.")

if __name__ == "__main__":
    scrape_new_vr_titles()
    # To run periodically (e.g., every 30 minutes), uncomment the loop below:
    # while True:
    #     scrape_new_vr_titles()
    #     print(f"Waiting for 30 minutes before next full scrape...")
    #     time.sleep(30 * 60)
