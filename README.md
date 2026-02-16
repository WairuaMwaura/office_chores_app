# Office Chore Management System

This is a simple, offline-first web application designed to manage kitchen chores in a small office. It is built with a Python FastAPI backend, a local MySQL database, and a plain HTML, CSS, and Vanilla JavaScript frontend.

The system is designed to be fully functional without an internet connection and prioritizes fairness and simplicity.

## Tech Stack

*   **Backend**: Python 3.8+ with FastAPI
*   **Database**: MySQL
*   **Frontend**: HTML, CSS, Vanilla JavaScript
*   **Web Server**: Uvicorn

## Setup and Installation

Follow these steps to get the application running on your local machine.

### Step 1: Database Setup (MySQL)

1.  Ensure you have a local MySQL server installed and running.
2.  Connect to your MySQL server and run the following command to create the database:
    ```sql
    CREATE DATABASE IF NOT EXISTS office_chores;
    ```
3.  You do **not** need to create the tables manually. The application will do this for you.

### Step 2: Backend Configuration

1.  **Navigate to the `backend` folder.**
2.  **Edit `database.py`**: Open the `backend/database.py` file and update the `db_config` dictionary with your MySQL username and password.

    ```python
    # backend/database.py
    db_config = {
        "host": "localhost",
        "user": "your_mysql_username",  # <-- CHANGE THIS
        "password": "your_mysql_password",  # <-- CHANGE THIS
        "database": "office_chores"
    }
    ```

3.  **Install Python Dependencies**: It is highly recommended to use a virtual environment.
    ```sh
    # Navigate to the backend directory
    cd backend

    # Create and activate a virtual environment (optional but recommended)
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

    # Install the required packages
    pip install -r requirements.txt
    ```

### Step 3: Running the Application

1.  **Initialize the Database Tables**:
    *   Make sure you are in the `backend` directory with your virtual environment activated.
    *   Run the FastAPI server:
        ```sh
        uvicorn main:app --reload
        ```
    *   Open your web browser and go to `http://127.0.0.1:8000/setup`. 
    * This will run the database initialization endpoint that we created. This will create the members, attendance, and chore_assignments tables for you.
    *   You should see a message: `{"message": "Database and tables initialized successfully."}`. This one-time step creates all the necessary tables.

2.  **Start Using the App**:
    *   With the server still running, navigate to the main page:
        **http://127.0.0.1:8000**
    *   The application is now ready to use.

## How to Use

1.  **Manage People**: Go to the "Manage People" page to add all the members of your office.
2.  **Mark Attendance**: On the main page (`/`), check the boxes for everyone who is present today.
3.  **Assign Chores**: Click the "Mark Attendance & Assign Chores" button. The system will display the assigned cooks and dish washer. If fewer than three people are present, a warning will be shown instead.
4.  **Check History**: Visit the "History" page to see a running total of chores assigned to ensure the system is working fairly over time.