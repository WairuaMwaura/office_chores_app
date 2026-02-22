# backend/logic.py

import random
from datetime import date, timedelta
from .database import get_db_connection, db_config
import mysql.connector
from mysql.connector import errorcode


# This new function runs once to safely add the new column for the "handicap" score.
# It will check if the column exists first, so it's safe to run every time.
def _add_score_adjustment_column_if_not_exists():
    """Checks for and adds the 'score_adjustment' column to the members table."""
    conn = get_db_connection()
    if not conn:
        print("DB connection failed, cannot check/update schema.")
        return
    cursor = conn.cursor()
    try:
        # This query checks the database's information schema to see if our column exists.
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{db_config["database"]}' 
            AND TABLE_NAME = 'members' 
            AND COLUMN_NAME = 'score_adjustment'
        """)
        if cursor.fetchone()[0] == 0:
            print("Column 'score_adjustment' not found. Adding it now...")
            cursor.execute(
                "ALTER TABLE members ADD COLUMN score_adjustment INT NOT NULL DEFAULT 0")
            conn.commit()
            print("Column 'score_adjustment' added successfully.")
    except mysql.connector.Error as err:
        print(f"Failed to alter table: {err}")
    finally:
        cursor.close()
        conn.close()


# Run the schema check once when the application starts.
_add_score_adjustment_column_if_not_exists()


def get_all_members_with_scores():
    """Helper function to get all active members and their current penalty scores."""
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor(dictionary=True)
    try:
        # This single, efficient query gets the chore count and adjustment for all members.
        cursor.execute("""
            SELECT 
                m.member_id, 
                m.name,
                m.score_adjustment,
                (SELECT COUNT(*) FROM chore_assignments ca WHERE ca.member_id = m.member_id) as chore_count
            FROM members m
            WHERE m.is_active = TRUE
        """)
        members = cursor.fetchall()
        for member in members:
            # The total penalty score is the sum of real chores and the adjustment.
            member['total_score'] = member['chore_count'] + member[
                'score_adjustment']
        return members
    finally:
        cursor.close()
        conn.close()


def add_member(name: str):
    """Adds a new member and sets their score adjustment to the current highest score."""
    conn = get_db_connection()
    if not conn: return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        # Step 1: Find the current highest penalty score.
        all_members = get_all_members_with_scores()
        highest_score = 0
        if all_members:
            highest_score = max(member['total_score'] for member in all_members)

        # Step 2: Insert the new member with the calculated score adjustment.
        cursor.execute(
            "INSERT INTO members (name, score_adjustment) VALUES (%s, %s)",
            (name, highest_score)
        )
        conn.commit()
        return {
            "message": f"Member '{name}' added successfully with starting score of {highest_score}."}
    except Exception as err:
        return {"error": f"Failed to add member: {err}"}
    finally:
        cursor.close()
        conn.close()


def assign_chores_for_today():
    """Main function to assign chores based on all-time history and new rules."""
    conn = get_db_connection()
    if not conn: return None, "Database connection failed."
    cursor = conn.cursor(dictionary=True)
    today = date.today()

    # --- NEW: Friday Rule Check ---
    is_friday = (today.weekday() == 4)
    min_required = 2 if is_friday else 3

    try:
        # Check if chores are already assigned for today
        cursor.execute(
            "SELECT * FROM chore_assignments WHERE assignment_date = %s",
            (today,))
        if cursor.fetchone():
            return None, "Chores have already been assigned for today."

        # Step 1: Get members present today
        cursor.execute(
            "SELECT m.member_id, m.name FROM members m "
            "JOIN attendance a ON m.member_id = a.member_id "
            "WHERE a.attendance_date = %s AND a.is_present = TRUE",
            (today,)
        )
        present_members_today = {p['member_id']: p for p in cursor.fetchall()}

        if len(present_members_today) < min_required:
            return None, f"Warning: Fewer than {min_required} people are present. Chores cannot be assigned."

        # Step 2: Get scores for ALL active members to filter from
        all_members_scores = get_all_members_with_scores()

        # Filter the list to only include members present today
        eligible_members = [
            member for member in all_members_scores
            if member['member_id'] in present_members_today
        ]

        # Step 3: Sort by total score (lowest first)
        eligible_members.sort(key=lambda x: x['total_score'])

        # --- NEW: Randomized Tie-Breaking ---
        # If the scores of the first few people are the same, shuffle them to randomize selection.
        if len(eligible_members) >= 2:
            first_score = eligible_members[0]['total_score']
            # Find all members who are tied for the lowest score
            tied_members = [m for m in eligible_members if
                            m['total_score'] == first_score]
            # Shuffle just that group of tied members
            random.shuffle(tied_members)
            # Replace the start of the main list with the shuffled tied members
            eligible_members[:len(tied_members)] = tied_members

        # Step 4: Assign chores
        assignments = {}
        assignment_data = []

        # Assign 2 Cooks
        cook1 = eligible_members[0]
        cook2 = eligible_members[1]
        assignments['cooks'] = [cook1['name'], cook2['name']]
        assignment_data.extend([
            (cook1['member_id'], 'Cooking', today),
            (cook2['member_id'], 'Cooking', today)
        ])

        # Assign Dish Washer only if it's NOT Friday
        if not is_friday:
            dish_washer = eligible_members[2]
            assignments['dish_washer'] = [dish_washer['name']]
            assignment_data.append(
                (dish_washer['member_id'], 'Washing Dishes', today))
        else:
            assignments['dish_washer'] = ["N/A (Friday)"]

        # Step 5: Persist assignments
        insert_cursor = conn.cursor()
        insert_cursor.executemany(
            "INSERT INTO chore_assignments (member_id, chore_type, assignment_date) VALUES (%s, %s, %s)",
            assignment_data
        )
        conn.commit()
        insert_cursor.close()

        return assignments, "Chores assigned successfully."
    except Exception as err:
        return None, f"An error occurred: {err}"
    finally:
        cursor.close()
        conn.close()

# --- Unchanged Functions ---
# (The rest of the functions from your original logic.py file go here)
# For brevity, I'll list them by name. Ensure they are still in your file.
# - remove_member(member_id: int)
# - get_active_members()
# - mark_attendance(present_member_ids: list[int], attendance_date_str: str)
# - get_daily_assignments(assignment_date: date)
# - get_history_summary() # You might want to update this to show total score + adjustment