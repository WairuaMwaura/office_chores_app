# backend/logic.py
import random
from datetime import date, timedelta
from .database import get_db_connection, db_config
import mysql.connector
from mysql.connector import errorcode


def _add_score_adjustment_column_if_not_exists():
    """Checks for and adds the 'score_adjustment' column to the members table."""
    conn = get_db_connection()
    if not conn:
        print("DB connection failed, cannot check/update schema.")
        return
    cursor = conn.cursor()
    try:
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
                "ALTER TABLE members ADD COLUMN score_adjustment FLOAT NOT NULL DEFAULT 0"
            )
            conn.commit()
            print("Column 'score_adjustment' added successfully.")
        else:
            # Ensure column is FLOAT in case it was previously INT
            cursor.execute(
                "ALTER TABLE members MODIFY COLUMN score_adjustment FLOAT NOT NULL DEFAULT 0"
            )
            conn.commit()
    except mysql.connector.Error as err:
        print(f"Failed to alter table: {err}")
    finally:
        cursor.close()
        conn.close()


# Run the schema check once when the application starts.
_add_score_adjustment_column_if_not_exists()


def _get_chore_rate(member_id: int, conn) -> float:
    """
    Calculates a member's chore rate: total chores done / total days attended (all-time).
    Returns 0.0 if the member has never attended.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s",
            (member_id,)
        )
        total_chores = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM attendance WHERE member_id = %s AND is_present = TRUE",
            (member_id,)
        )
        total_days_present = cursor.fetchone()[0]

        if total_days_present == 0:
            return 0.0
        return total_chores / total_days_present
    finally:
        cursor.close()


def get_all_members_with_scores():
    """
    Returns all active members with their chore rate (chores / days attended, all-time).
    New members get their rate from score_adjustment (set at join time).
    """
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT member_id, name, score_adjustment FROM members WHERE is_active = TRUE"
        )
        members = cursor.fetchall()
        for member in members:
            actual_rate = _get_chore_rate(member['member_id'], conn)
            # Use whichever is higher: actual rate or the handicap assigned at join time
            member['chore_rate'] = max(actual_rate, member['score_adjustment'])
        return members
    finally:
        cursor.close()
        conn.close()


def _get_highest_chore_rate(conn) -> float:
    """Returns the highest chore rate among all active members."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT member_id FROM members WHERE is_active = TRUE"
        )
        members = cursor.fetchall()
        if not members:
            return 0.0
        rates = [_get_chore_rate(m['member_id'], conn) for m in members]
        return max(rates) if rates else 0.0
    finally:
        cursor.close()


def add_member(name: str):
    """
    Adds a new member. Their score_adjustment is set to the current highest
    chore rate so they start on equal footing with the most active member.
    """
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        highest_rate = _get_highest_chore_rate(conn)
        cursor.execute(
            "INSERT INTO members (name, score_adjustment) VALUES (%s, %s)",
            (name, highest_rate)
        )
        conn.commit()
        return {
            "message": f"Member '{name}' added successfully with starting chore rate of {highest_rate:.2f}."
        }
    except Exception as err:
        return {"error": f"Failed to add member: {err}"}
    finally:
        cursor.close()
        conn.close()


def remove_member(member_id: int):
    """Deactivates a member. We don't delete to preserve history."""
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE members SET is_active = FALSE WHERE member_id = %s",
            (member_id,)
        )
        conn.commit()
        return {"message": f"Member with ID {member_id} has been removed."}
    except Exception as err:
        return {"error": f"Failed to remove member: {err}"}
    finally:
        cursor.close()
        conn.close()


def get_active_members():
    """Retrieves a list of all active members."""
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT member_id, name FROM members WHERE is_active = TRUE ORDER BY name"
        )
        return cursor.fetchall()
    except Exception as err:
        print(f"Failed to get members: {err}")
        return []
    finally:
        cursor.close()
        conn.close()


def mark_attendance(present_member_ids: list[int], attendance_date_str: str):
    """Marks the attendance for the given date."""
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    attendance_date = date.fromisoformat(attendance_date_str)
    try:
        all_members = get_active_members()
        for member in all_members:
            is_present = member['member_id'] in present_member_ids
            cursor.execute(
                "REPLACE INTO attendance (member_id, attendance_date, is_present) VALUES (%s, %s, %s)",
                (member['member_id'], attendance_date, is_present)
            )
        conn.commit()
        return {"message": "Attendance marked successfully."}
    except Exception as err:
        return {"error": f"Failed to mark attendance: {err}"}
    finally:
        cursor.close()
        conn.close()


def assign_chores_for_today():
    """
    Assigns chores based on chore rate (chores / days attended, all-time).
    - Members with lower chore rates are more likely to be selected.
    - Selection is weighted random among all eligible present members.
    - On Fridays, only 2 cooks are assigned (no dish washer).
    - Minimum 3 required on non-Fridays, minimum 2 on Fridays.
    """
    conn = get_db_connection()
    if not conn:
        return None, "Database connection failed."
    cursor = conn.cursor(dictionary=True)
    today = date.today()

    is_friday = (today.weekday() == 4)
    min_required = 2 if is_friday else 3
    chores_to_assign = 2 if is_friday else 3

    try:
        # Check if chores already assigned today
        cursor.execute(
            "SELECT * FROM chore_assignments WHERE assignment_date = %s",
            (today,)
        )
        if cursor.fetchone():
            return None, "Chores have already been assigned for today."

        # Get members present today
        cursor.execute(
            "SELECT m.member_id, m.name FROM members m "
            "JOIN attendance a ON m.member_id = a.member_id "
            "WHERE a.attendance_date = %s AND a.is_present = TRUE",
            (today,)
        )
        present_today = {p['member_id']: p['name'] for p in cursor.fetchall()}

        if len(present_today) < min_required:
            return None, f"Warning: Fewer than {min_required} people are present. Chores cannot be assigned."

        # Get chore rates, filter to present members only
        all_members = get_all_members_with_scores()
        eligible = [m for m in all_members if m['member_id'] in present_today]

        if len(eligible) < chores_to_assign:
            return None, "Not enough eligible members to assign chores."

        # Weighted random: lower chore rate = higher chance of selection
        max_rate = max(m['chore_rate'] for m in eligible) + 0.01
        weights = [max_rate - m['chore_rate'] + 0.01 for m in eligible]

        # Select unique members
        selected_ids = set()
        selected = []
        attempts = 0
        while len(selected) < chores_to_assign and attempts < 500:
            pick = random.choices(eligible, weights=weights, k=1)[0]
            if pick['member_id'] not in selected_ids:
                selected.append(pick)
                selected_ids.add(pick['member_id'])
            attempts += 1

        # Fallback to random sample if weighted selection failed
        if len(selected) < chores_to_assign:
            selected = random.sample(eligible, chores_to_assign)

        # Build assignments
        assignments = {}
        assignment_data = []

        cook1, cook2 = selected[0], selected[1]
        assignments['cooks'] = [cook1['name'], cook2['name']]
        assignment_data.extend([
            (cook1['member_id'], 'Cooking', today),
            (cook2['member_id'], 'Cooking', today),
        ])

        if not is_friday:
            dish_washer = selected[2]
            assignments['dish_washer'] = [dish_washer['name']]
            assignment_data.append(
                (dish_washer['member_id'], 'Washing Dishes', today)
            )
        else:
            assignments['dish_washer'] = ["N/A (Friday)"]

        # Persist to DB
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


def get_daily_assignments(assignment_date: date):
    """Retrieves assigned chores for a specific date."""
    conn = get_db_connection()
    if not conn:
        return {}
    cursor = conn.cursor(dictionary=True)
    assignments = {'cooks': [], 'dish_washer': []}
    try:
        cursor.execute(
            "SELECT m.name, ca.chore_type FROM chore_assignments ca "
            "JOIN members m ON ca.member_id = m.member_id "
            "WHERE ca.assignment_date = %s",
            (assignment_date,)
        )
        for row in cursor.fetchall():
            if row['chore_type'] == 'Cooking':
                assignments['cooks'].append(row['name'])
            else:
                assignments['dish_washer'].append(row['name'])
        return assignments
    finally:
        cursor.close()
        conn.close()


def get_history_summary():
    """
    Generates a summary of each active member's all-time chore stats and chore rate.
    """
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT member_id, name FROM members WHERE is_active = TRUE ORDER BY name"
        )
        members = cursor.fetchall()
        summary = []
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())

        for member in members:
            mid = member['member_id']

            # Total chores all-time
            cursor.execute(
                "SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s",
                (mid,)
            )
            total_chores = cursor.fetchone()['total']

            # Days present all-time
            cursor.execute(
                "SELECT COUNT(*) as total FROM attendance WHERE member_id = %s AND is_present = TRUE",
                (mid,)
            )
            days_present = cursor.fetchone()['total']

            chore_rate = round(total_chores / days_present, 3) if days_present > 0 else 0.0

            # Chores this week
            cursor.execute(
                "SELECT COUNT(*) as total FROM chore_assignments "
                "WHERE member_id = %s AND assignment_date >= %s",
                (mid, start_of_week)
            )
            chores_this_week = cursor.fetchone()['total']

            summary.append({
                "name": member['name'],
                "total_chores": total_chores,
                "days_present": days_present,
                "chore_rate": chore_rate,
                "chores_this_week": chores_this_week,
            })
        return summary
    finally:
        cursor.close()
        conn.close()