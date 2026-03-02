# backend/logic.py
import random
from datetime import date, timedelta
from .database import get_db_connection, db_config
import mysql.connector
from mysql.connector import errorcode


def _add_score_adjustment_column_if_not_exists():
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
        else:
            cursor.execute(
                "ALTER TABLE members MODIFY COLUMN score_adjustment FLOAT NOT NULL DEFAULT 0"
            )
            conn.commit()
    except mysql.connector.Error as err:
        print(f"Failed to alter table: {err}")
    finally:
        cursor.close()
        conn.close()


_add_score_adjustment_column_if_not_exists()


def _get_chore_rate(member_id: int, conn) -> float:
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
            member['chore_rate'] = max(actual_rate, member['score_adjustment'])
        return members
    finally:
        cursor.close()
        conn.close()


def _get_highest_chore_rate(conn) -> float:
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT member_id FROM members WHERE is_active = TRUE")
        members = cursor.fetchall()
        if not members:
            return 0.0
        rates = [_get_chore_rate(m['member_id'], conn) for m in members]
        return max(rates) if rates else 0.0
    finally:
        cursor.close()


def add_member(name: str):
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
        return {"message": f"Member '{name}' added successfully with starting chore rate of {highest_rate:.2f}."}
    except Exception as err:
        return {"error": f"Failed to add member: {err}"}
    finally:
        cursor.close()
        conn.close()


def remove_member(member_id: int):
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


def get_absent_members_today():
    """Returns active members who are absent or unrecorded for today."""
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    try:
        cursor.execute("""
            SELECT m.member_id, m.name
            FROM members m
            WHERE m.is_active = TRUE
            AND m.member_id NOT IN (
                SELECT member_id FROM attendance
                WHERE attendance_date = %s AND is_present = TRUE
            )
            ORDER BY m.name
        """, (today,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_todays_chore_status():
    """
    Returns current chore assignments for today and whether slots are still open.
    Used to determine late arrival options.
    """
    conn = get_db_connection()
    if not conn:
        return None
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    is_friday = (today.weekday() == 4)
    try:
        cursor.execute("""
            SELECT ca.assignment_id, ca.member_id, ca.chore_type, m.name
            FROM chore_assignments ca
            JOIN members m ON ca.member_id = m.member_id
            WHERE ca.assignment_date = %s
        """, (today,))
        assignments = cursor.fetchall()

        cooks = [a for a in assignments if a['chore_type'] == 'Cooking']
        dish_washers = [a for a in assignments if a['chore_type'] == 'Washing Dishes']

        cooks_filled = len(cooks) >= 2
        dish_filled = len(dish_washers) >= 1 or is_friday

        return {
            "chores_assigned": len(assignments) > 0,
            "is_friday": is_friday,
            "cooks": cooks,
            "dish_washers": dish_washers,
            "cooks_filled": cooks_filled,
            "dish_filled": dish_filled,
            "fully_staffed": cooks_filled and dish_filled,
        }
    finally:
        cursor.close()
        conn.close()


def mark_late_arrival(member_id: int, action: str, swap_assignment_id: int = None):
    """
    Records a late arrival and handles chore reassignment if needed.

    action:
      - "attendance_only"  : just mark them present, no chore changes
      - "fill_gap"         : assign them to an unfilled chore slot
      - "swap_dishes"      : they take over dish washing; original washer's score is reversed
    """
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    is_friday = (today.weekday() == 4)

    try:
        # 1. Mark them present today
        cursor.execute("""
            REPLACE INTO attendance (member_id, attendance_date, is_present)
            VALUES (%s, %s, TRUE)
        """, (member_id, today))

        if action == "attendance_only":
            conn.commit()
            return {"message": "Attendance recorded. No chore changes made."}

        elif action == "fill_gap":
            # Determine which slot is open
            status = get_todays_chore_status()
            if not status or status['fully_staffed']:
                conn.commit()
                return {"error": "No open chore slots to fill."}

            if len(status['cooks']) < 2:
                chore_type = 'Cooking'
            elif not status['dish_filled'] and not is_friday:
                chore_type = 'Washing Dishes'
            else:
                conn.commit()
                return {"error": "No open chore slots to fill."}

            cursor.execute("""
                INSERT INTO chore_assignments (member_id, chore_type, assignment_date)
                VALUES (%s, %s, %s)
            """, (member_id, chore_type, today))
            conn.commit()
            return {"message": f"Attendance recorded and assigned to {chore_type}."}

        elif action == "swap_dishes":
            if not swap_assignment_id:
                return {"error": "No assignment ID provided for swap."}

            # Get the original dish washer assignment
            cursor.execute("""
                SELECT * FROM chore_assignments
                WHERE assignment_id = %s AND chore_type = 'Washing Dishes'
            """, (swap_assignment_id,))
            original = cursor.fetchone()
            if not original:
                return {"error": "Original dish washer assignment not found."}

            original_member_id = original['member_id']

            # Remove the original dish washer assignment
            cursor.execute(
                "DELETE FROM chore_assignments WHERE assignment_id = %s",
                (swap_assignment_id,)
            )

            # Assign the latecomer to dish washing
            cursor.execute("""
                INSERT INTO chore_assignments (member_id, chore_type, assignment_date)
                VALUES (%s, 'Washing Dishes', %s)
            """, (member_id, today))

            conn.commit()
            return {
                "message": f"Attendance recorded. Dish washing reassigned. Original member's score has been adjusted.",
                "original_member_id": original_member_id
            }

        else:
            return {"error": f"Unknown action: {action}"}

    except Exception as err:
        return {"error": f"Failed to process late arrival: {err}"}
    finally:
        cursor.close()
        conn.close()


def mark_attendance(present_member_ids: list[int], attendance_date_str: str):
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
    conn = get_db_connection()
    if not conn:
        return None, "Database connection failed."
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    is_friday = (today.weekday() == 4)
    min_required = 2 if is_friday else 3
    chores_to_assign = 2 if is_friday else 3

    try:
        cursor.execute(
            "SELECT * FROM chore_assignments WHERE assignment_date = %s", (today,))
        if cursor.fetchone():
            return None, "Chores have already been assigned for today."

        cursor.execute(
            "SELECT m.member_id, m.name FROM members m "
            "JOIN attendance a ON m.member_id = a.member_id "
            "WHERE a.attendance_date = %s AND a.is_present = TRUE",
            (today,)
        )
        present_today = {p['member_id']: p['name'] for p in cursor.fetchall()}

        if len(present_today) < min_required:
            return None, f"Warning: Fewer than {min_required} people are present. Chores cannot be assigned."

        all_members = get_all_members_with_scores()
        eligible = [m for m in all_members if m['member_id'] in present_today]

        if len(eligible) < chores_to_assign:
            return None, "Not enough eligible members to assign chores."

        max_rate = max(m['chore_rate'] for m in eligible) + 0.01
        weights = [max_rate - m['chore_rate'] + 0.01 for m in eligible]

        selected_ids = set()
        selected = []
        attempts = 0
        while len(selected) < chores_to_assign and attempts < 500:
            pick = random.choices(eligible, weights=weights, k=1)[0]
            if pick['member_id'] not in selected_ids:
                selected.append(pick)
                selected_ids.add(pick['member_id'])
            attempts += 1

        if len(selected) < chores_to_assign:
            selected = random.sample(eligible, chores_to_assign)

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
            assignment_data.append((dish_washer['member_id'], 'Washing Dishes', today))
        else:
            assignments['dish_washer'] = ["N/A (Friday)"]

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
    conn = get_db_connection()
    if not conn:
        return {}
    cursor = conn.cursor(dictionary=True)
    assignments = {'cooks': [], 'dish_washer': []}
    try:
        cursor.execute(
            "SELECT m.name, ca.chore_type, ca.assignment_id, ca.member_id "
            "FROM chore_assignments ca "
            "JOIN members m ON ca.member_id = m.member_id "
            "WHERE ca.assignment_date = %s",
            (assignment_date,)
        )
        for row in cursor.fetchall():
            if row['chore_type'] == 'Cooking':
                assignments['cooks'].append(row['name'])
            else:
                assignments['dish_washer'].append({
                    'name': row['name'],
                    'assignment_id': row['assignment_id'],
                    'member_id': row['member_id']
                })
        return assignments
    finally:
        cursor.close()
        conn.close()


def get_history_summary():
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

            cursor.execute(
                "SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s", (mid,))
            total_chores = cursor.fetchone()['total']

            cursor.execute(
                "SELECT COUNT(*) as total FROM attendance WHERE member_id = %s AND is_present = TRUE", (mid,))
            days_present = cursor.fetchone()['total']

            chore_rate = round(total_chores / days_present, 3) if days_present > 0 else 0.0

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