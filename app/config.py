import os


class Config:
    SECRET_KEY = "change-this-in-production"

    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

    # Database file name
    DB_PATH = os.path.join(INSTANCE_DIR, "ezzystore.db")
