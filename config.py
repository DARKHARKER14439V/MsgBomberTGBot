import os

class Config(object):
    # Bot token (Render se aayega)
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    # Authorized users
    AUTH_USERS = [8124480686]

    # Protected numbers
    NO_BOMB_NUMS = []

    # Admin / sudo users
    GOD_USERS = [693236796, 1074732684]
