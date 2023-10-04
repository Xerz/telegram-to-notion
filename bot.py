import os
import sqlite3
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from decouple import config
from notion_client import Client

# Load credentials from the .env file
TELEGRAM_BOT_TOKEN = config('TELEGRAM_BOT_TOKEN')

# SQLite database file
DB_FILE = 'bot_db.sqlite'

# Helper function to create tables if they don't exist
def create_tables():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        database_id TEXT,
                        notion_secret TEXT
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
                        message_id INTEGER PRIMARY KEY,
                        row_id TEXT
                    )''')
    conn.commit()
    conn.close()

# Function to get the selected database ID and Notion secret from the database
def get_selected_db_and_secret(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT database_id, notion_secret FROM users WHERE user_id=?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

# Function to add an entry as a block inside the selected Notion page
def add_entry_to_notion_db(entry_text, parent_row_id=None, message_id=None, chat_id=None):
    notion_secret = get_notion_secret(chat_id)

    if not notion_secret:
        return False

    try:
        notion = Client(auth=notion_secret)
        database_id = get_selected_database_id(chat_id)  # Use the collection_id stored in the database

        if not database_id:
            return False

        # collection = notion.databases.retrieve(database_id)

        if parent_row_id:
            # Find the corresponding row
            row = notion.blocks.retrieve(parent_row_id)

            if row:
                # Add the message as a block inside the page
                new_block = notion.blocks.children.append(
                    block_id=parent_row_id,
                    children=[{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": entry_text}}]
                        }
                    }]
                )

                # Store the pair of message_id and row_id in the local database
                store_message_row_pair(message_id, parent_row_id)

                return True
        else:
            # Create a new row and add the message as a block
            new_page = notion.pages.create(
                parent={"type": "database_id", "database_id": database_id},
                properties={"title": [{"text": {"content": entry_text}}]}
            )


            # Store the pair of message_id and row_id in the local database
            store_message_row_pair(message_id, new_page["id"])

            return True
    except Exception as e:
        print(e)
        return False

# Helper function to store the pair of message_id and row_id in the local database
def store_message_row_pair(message_id, row_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages (message_id, row_id) VALUES (?, ?)", (message_id, row_id))
    conn.commit()
    conn.close()

# Telegram /start command handler
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome to the Notion Bot!\nUse /add to add an entry to the selected Notion database.")
    update.message.reply_text("Use /setdb to set the Notion database ID and secret.")

# Telegram /add command handler
def add_entry(update: Update, context: CallbackContext):
    entry_text = context.args[0] if context.args else update.message.text
    parent_row_id = None
    message_id = update.message.message_id  # Get the message_id
    chat_id = update.message.chat_id  # Get the chat_id

    if update.message.reply_to_message:
        # Check if it's a reply to a message, and if so, get the parent_row_id from the local database
        parent_message_id = update.message.reply_to_message.message_id

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT row_id FROM messages WHERE message_id=?", (parent_message_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            parent_row_id = result[0]

    if add_entry_to_notion_db(entry_text, parent_row_id, message_id, chat_id):
        update.message.reply_text("Your message has been added to the Notion database.")
    else:
        update.message.reply_text("Failed to add your message to the Notion database. Please try again.")

# Telegram /setdb command handler
def set_database(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        update.message.reply_text("Please the Notion database ID with the /setdb command.")
        return

    database_id = context.args[0]
    chat_id = update.message.chat_id  # Get the chat_id

    notion_secret = get_notion_secret(chat_id=chat_id)
    # Store the selected database ID and Notion secret in the SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, database_id, notion_secret) VALUES (?, ?, ?)", (chat_id, database_id, notion_secret))
    conn.commit()
    conn.close()

    update.message.reply_text(f"You have selected the Notion database with ID: {database_id} and associated Notion secret.")

# Helper function to get the selected database ID from the database
def get_selected_database_id(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT database_id FROM users WHERE user_id=?", (chat_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Helper function to get the Notion secret from the database
def get_notion_secret(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT notion_secret FROM users WHERE user_id=?", (chat_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Telegram /setsecret command handler
def set_secret(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        update.message.reply_text("Please provide your Notion secret with the /setsecret command.")
        return

    notion_secret = context.args[0]
    chat_id = update.message.chat_id  # Get the chat_id

    database_id = get_selected_database_id(chat_id=chat_id)
    # Store the Notion secret in the SQLite database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, database_id, notion_secret) VALUES (?, ?, ?)", (chat_id, database_id, notion_secret))
    conn.commit()
    conn.close()

    update.message.reply_text("Your Notion secret has been set and associated with your user.")

# Initialize the Telegram bot
if __name__ == '__main__':
    create_tables()

updater = Updater(token=TELEGRAM_BOT_TOKEN)
dispatcher = updater.dispatcher

# Register command handlers
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CommandHandler('add', add_entry, pass_args=True))
dispatcher.add_handler(CommandHandler('setdb', set_database, pass_args=True))
dispatcher.add_handler(CommandHandler('setsecret', set_secret, pass_args=True))
dispatcher.add_handler(MessageHandler(Filters.text, add_entry))

# Start polling for updates
updater.start_polling()
updater.idle()
