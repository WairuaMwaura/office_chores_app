import os

import mysql.connector
from mysql.connector import errorcode

# --- IMPORTANT: DATABASE CONFIGURATION ---
# Please update these values with your local MySQL credentials.
db_config = {
    "host": os.environ.get("MYSQLHOST", "localhost"),
    "port": int(os.environ.get("MYSQLPORT") or 3306),
    "user": os.environ.get("MYSQLUSER", "root"),
    "password": os.environ.get("MYSQLPASSWORD", ""),
    "database": os.environ.get("MYSQLDATABASE", "office-chores"),
}


def get_db_connection():
    """Establishes and returns a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            database=db_config["database"]
        )
        return conn
    except mysql.connector.Error as err:
        # If the database doesn't exist, it will be created by the setup function
        if err.errno == errorcode.ER_BAD_DB_ERROR:
            print("Database 'office_chores' does not exist.")
            return None
        print(f"Error connecting to database: {err}")
        return None


def setup_database_and_tables():
    """
    Connects to MySQL server, creates the database if it doesn't exist,
    and then creates the necessary tables.
    """
    try:
        # Connect without specifying a database to create it
        conn = mysql.connector.connect(
            host=db_config["host"],
            user=db_config["user"],
            password=db_config["password"]
        )
        cursor = conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS {db_config['database']} CHARACTER SET utf8mb4")
        print(f"Database '{db_config['database']}' created or already exists.")
        cursor.close()
        conn.close()
    except mysql.connector.Error as err:
        print(f"Failed to create database: {err}")
        exit(1)

    # Now connect to the specific database to create tables
    conn = get_db_connection()
    if not conn:
        print("Could not connect to the database after creation. Aborting.")
        return

    cursor = conn.cursor()

    tables = {
        "members": (
            "CREATE TABLE `members` ("
            "  `member_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `name` VARCHAR(255) NOT NULL UNIQUE,"
            "  `is_active` BOOLEAN DEFAULT TRUE,"
            "  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ") ENGINE=InnoDB"
        ),
        "attendance": (
            "CREATE TABLE `attendance` ("
            "  `attendance_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `member_id` INT,"
            "  `attendance_date` DATE NOT NULL,"
            "  `is_present` BOOLEAN NOT NULL,"
            "  FOREIGN KEY (`member_id`) REFERENCES `members`(`member_id`) ON DELETE CASCADE,"
            "  UNIQUE KEY `uq_attendance` (`member_id`, `attendance_date`)"
            ") ENGINE=InnoDB"
        ),
        "chore_assignments": (
            "CREATE TABLE `chore_assignments` ("
            "  `assignment_id` INT AUTO_INCREMENT PRIMARY KEY,"
            "  `member_id` INT,"
            "  `chore_type` ENUM('Cooking', 'Washing Dishes') NOT NULL,"
            "  `assignment_date` DATE NOT NULL,"
            "  FOREIGN KEY (`member_id`) REFERENCES `members`(`member_id`) ON DELETE CASCADE"
            ") ENGINE=InnoDB"
        )
    }

    for name, ddl in tables.items():
        try:
            print(f"Creating table {name}: ", end='')
            cursor.execute(ddl)
            print("OK")
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                print("already exists.")
            else:
                print(err.msg)

    cursor.close()
    conn.close()