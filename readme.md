# Cookie Clicker Bot

This script automates the game [Cookie Clicker](https://orteil.dashnet.org/cookieclicker/) using Selenium WebDriver. It performs various actions in the game to maximize cookie production even when while away.

## Prerequisites

- Python 3.x
- Selenium
- ChromeDriver
- numpy

## Setup

1. Install Selenium & numpy:
    ```sh
    pip install selenium, numpy
    ```

2. Download the appropriate version of ChromeDriver (or any other driver with a small adjustment in the cookiebot.py file) from [here]([webdriver](https://www.npmjs.com/package/selenium-webdriver)) and place it in your PATH.

## Usage

1. To clone this repository, use the following command:
    ```sh
    git clone <repository_url>
    ```
2. Navigate to the directory:
    ```sh
    cd <directory_name>
    ```
3. Run the bot using `cookieBot.py`:
    ```sh
    python cookieBot.py
    ```
## Why use this Cookie Clicker bot?

I created this bot a while back and thought to publicize it since it turned out quite useful to be able to afk the game and still get golden cookies or even be able to make use of Force of hand when a good golden cookie multiplier occurs.

## How to import a save file?

The bot will automatically make use of a file in the same folder called: CookieAISaveData.txt, you can export your old save data to a file and rename it as such to import it or you can change the contents of the file and restart the bot to change the file. It is always recommended to restart the bot when a save file is used or when you prestige so the bot is properly initialized.

# Features of the Cookie Clicker Bot

The Cookie Clicker Bot automates various aspects of the [Cookie Clicker](https://orteil.dashnet.org/cookieclicker/) game to enhance the player's experience and optimize cookie production. Below are the key features of the bot:

## Automated Cookie Clicking

- **Continuous Cookie Clicking**: The bot automatically clicks the main cookie at a fast rate so you don't really have to yourself.

## Golden Cookie Management

- **Golden Cookie Clicking**: The bot detects and clicks Golden Cookies as soon as they appear to take advantage of their bonuses.

- **Golden Cookie Combo**: This bot can also use force of hand or take loans when a good golden cookie bonus occurs.

## Building Management

- **Building Purchase**: The bot evaluates and purchases buildings based on their cost-effectiveness to increase cookies per second (CPS).

## Upgrade Management

- **Upgrade Purchase**: The bot evaluates and purchases upgrades, considering both general and specific upgrades, to optimize CPS and click efficiency.

## Heuristic Evaluation

- **Heuristic Calculations**: The bot uses heuristics to determine the best buildings and upgrades to purchase based on their impact on CPS relative to their cost.

## Save and Load Game Data

- **Automatic Game Save**: The bot periodically saves the game's progress to a local file.
- **Automatic Game Load**: The bot can load game data from a local file to resume from the last saved state.

## Sugar Lump Management

- **Sugar Lump Harvesting**: The bot periodically checks and harvests sugar lumps to utilize their benefits.

## Garden Management

- **Garden Management**: The bot manages the garden by planting clovers to optimize golden cookies.

## Stock Market Interaction

- **Stock Market Check**: The bot interacts with the stock market, evaluating and performing actions to maximize profit from stock trades.

## Periodic Actions

- **Scheduled Tasks**: The bot performs specific actions, such as upgrading and managing resources, at regular intervals to ensure optimal gameplay.

# Is this Cheating?

This is obviously not the way the game was meant to be played, but the game was intentionally designed so users can make use of commands in the command line, even allowing you to set your cookies to any number you want.
This bot was intended to only do things so you don't have, not to do things you couldn't do yourself. Using this bot will **not** get you the [cheated cookies](https://cookieclicker.fandom.com/wiki/Cheating#:~:text=to%20decimal%20converter-,%22Cheated%20cookies%20taste%20awful%22%20Achievement,adjusted%20depending%20on%20the%20CpS.) shadow achievement.
