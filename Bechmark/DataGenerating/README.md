# Catawiki Auction Scraper

This directory contains scripts to scrape auction data from Catawiki.com

## Installation

### Option 1: Using pip (Recommended)
```bash
pip install selenium webdriver-manager requests beautifulsoup4
```

### Option 2: Using system packages
```bash
sudo apt-get update
sudo apt-get install python3-selenium python3-requests chromium-browser chromium-chromedriver
```

### Option 3: Manual installation
```bash
# Download and install ChromeDriver manually
wget https://chromedriver.storage.googleapis.com/LATEST_RELEASE
# Follow instructions at: https://chromedriver.chromium.org/downloads
```

## Usage

### Basic Usage
```bash
cd /mnt/data/user/fengxian.ji/AUCTION/DataGenerating

# Using Selenium (recommended for Catawiki)
python3 catawiki_scraper_selenium.py

# Or specify custom URL and folder number
python3 catawiki_scraper_selenium.py "https://www.catawiki.com/en/l/XXXXXX" 2
```

### Custom Parameters
```bash
# Scrape specific URL to folder number 2
python3 catawiki_scraper_selenium.py "https://www.catawiki.com/en/l/12345678-item-name" 2
```

## Output Structure

The scraper creates the following structure:
```
benchmark/EmergingArt/
└── 1/                          # Folder number
    ├── figure/                 # Images folder
    │   ├── 1.jpg
    │   ├── 2.jpg
    │   └── 3.jpg
    ├── description.txt         # Item description
    └── growth.json            # Pricing and bid history
```

### growth.json Format
```json
{
  "starting_price": "€100",
  "final_price": "€250",
  "bid_history": [
    {"bid_number": 1, "price": "€100"},
    {"bid_number": 2, "price": "€150"},
    {"bid_number": 3, "price": "€250"}
  ]
}
```

## Scripts

- `catawiki_scraper.py` - Basic scraper using requests and BeautifulSoup
- `catawiki_scraper_selenium.py` - Advanced scraper using Selenium (handles JavaScript, bypasses bot detection)

## Troubleshooting

### ModuleNotFoundError: No module named 'selenium'
Install selenium: `pip install selenium webdriver-manager`

### WebDriver not found
Install chromedriver: `sudo apt-get install chromium-chromedriver`

### 403 Access Denied
Use the Selenium version (`catawiki_scraper_selenium.py`) which better handles anti-bot protection.

## Notes

- Catawiki has anti-scraping protection, so the Selenium version is recommended
- Be respectful of the website's resources (the script includes delays)
- The scraper may need updates if Catawiki changes their HTML structure


数据整理的三个阶段
1.整体数据处理
/mnt/data/user/fengxian.ji/AUCTION/DataGenerating/pipeline.py

2.人主动进行筛选，检查

3.数据拆分
我这里首先按照价格将这里的数据选择成3份的方式
混合
这里需要具体看然后去给出这里的价格

分层随机抽样得到这里的/mnt/data/user/fengxian.ji/AUCTION/benchmark/EmergingArt_test100

这里的描述部分需要用这里的llm进行修改，以及这里去整理