from datetime import date, timedelta
from .database import get_db_connection


def add_member(name: str):
    """Adds a new member to the office list."""
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO members (name) VALUES (%s)", (name,))
        conn.commit()
        return {"message": f"Member '{name}' added successfully."}
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
            (member_id,))
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
            "SELECT member_id, name FROM members WHERE is_active = TRUE ORDER BY name")
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


def get_chore_history_score(member_id: int, start_date: date, end_date: date):
    """Calculates the number of chores for a member in a date range."""
    conn = get_db_connection()
    if not conn: return 0
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s AND assignment_date BETWEEN %s AND %s",
            (member_id, start_date, end_date)
        )
        score = cursor.fetchone()[0]
        return score
    except Exception:
        return 0
    finally:
        cursor.close()
        conn.close()


def assign_chores_for_today():
    """The main function to assign chores based on fairness rules for today."""
    conn = get_db_connection()
    if not conn:
        return None, "Database connection failed."
    cursor = conn.cursor(dictionary=True)
    today = date.today()

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
        present_members = cursor.fetchall()

        # Step 2: Check for minimum attendance
        if len(present_members) < 3:
            return None, "Warning: Fewer than 3 people are present. Chores cannot be assigned."

        # Step 3: Calculate historical scores (last 14 days)
        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=13)

        member_scores = []
        for member in present_members:
            score = get_chore_history_score(member['member_id'], start_date,
                                            end_date)
            member_scores.append(
                {'member_id': member['member_id'], 'name': member['name'],
                 'score': score})

        # Step 4: Prioritize members with lower scores
        member_scores.sort(key=lambda x: x['score'])

        # Step 5: Assign chores
        cooks = [member_scores[0], member_scores[1]]
        dish_washer = member_scores[2]

        # Step 6: Persist assignments
        assignment_data = [
            (cooks[0]['member_id'], 'Cooking', today),
            (cooks[1]['member_id'], 'Cooking', today),
            (dish_washer['member_id'], 'Washing Dishes', today)
        ]
        insert_cursor = conn.cursor()
        insert_cursor.executemany(
            "INSERT INTO chore_assignments (member_id, chore_type, assignment_date) VALUES (%s, %s, %s)",
            assignment_data
        )
        conn.commit()
        insert_cursor.close()

        assignments = {
            'cooks': [cooks[0]['name'], cooks[1]['name']],
            'dish_washer': [dish_washer['name']]
        }
        return assignments, "Chores assigned successfully."
    except Exception as err:
        return None, f"An error occurred: {err}"
    finally:
        cursor.close()
        conn.close()


def get_daily_assignments(assignment_date: date):
    """Retrieves assigned chores for a specific date."""
    conn = get_db_connection()
    if not conn: return {}
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
    """Generates a summary of chores for the last two weeks."""
    conn = get_db_connection()
    if not conn: return []
    cursor = conn.cursor(dictionary=True)

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_last_2_weeks = today - timedelta(days=13)

    members = get_active_members()
    summary = []

    for member in members:
        chores_this_week = get_chore_history_score(member['member_id'],
                                                   start_of_week, today)
        chores_last_2_weeks = get_chore_history_score(member['member_id'],
                                                      start_of_last_2_weeks,
                                                      today)
        summary.append({
            "name": member['name'],
            "chores_this_week": chores_this_week,
            "chores_last_2_weeks": chores_last_2_weeks
        })
    return summary