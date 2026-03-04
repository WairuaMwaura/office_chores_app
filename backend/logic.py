# backend/logic.py
import random
import math
from datetime import date, timedelta
from .database import get_db_connection, db_config
import mysql.connector


def _add_score_adjustment_column_if_not_exists():
    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{db_config["database"]}'
            AND TABLE_NAME = 'members' AND COLUMN_NAME = 'score_adjustment'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE members ADD COLUMN score_adjustment FLOAT NOT NULL DEFAULT 0")
        else:
            cursor.execute("ALTER TABLE members MODIFY COLUMN score_adjustment FLOAT NOT NULL DEFAULT 0")
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
        cursor.execute("SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s", (member_id,))
        total_chores = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE member_id = %s AND is_present = TRUE", (member_id,))
        total_days_present = cursor.fetchone()[0]
        if total_days_present == 0:
            return 0.0
        return total_chores / total_days_present
    finally:
        cursor.close()


def _did_chore_yesterday(member_id: int, conn) -> bool:
    """Returns True if this member was assigned any chore yesterday."""
    yesterday = date.today() - timedelta(days=1)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s AND assignment_date = %s",
            (member_id, yesterday)
        )
        return cursor.fetchone()[0] > 0
    finally:
        cursor.close()


def _get_members_who_did_chore_yesterday(conn) -> set:
    """Returns set of member_ids who did any chore yesterday."""
    yesterday = date.today() - timedelta(days=1)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT DISTINCT member_id FROM chore_assignments WHERE assignment_date = %s",
            (yesterday,)
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()


def get_all_members_with_scores():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT member_id, name, score_adjustment FROM members WHERE is_active = TRUE")
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


def _select_weighted_unique(eligible: list, k: int, did_yesterday: set) -> list:
    """
    Selects k unique members using exponential inverse weighting on chore rate.
    Members who did a chore yesterday are excluded UNLESS there aren't enough
    others to fill all slots (i.e. everyone present did chores yesterday).
    """
    DECAY = 4.0

    # Try to exclude yesterday's workers first
    preferred = [m for m in eligible if m['member_id'] not in did_yesterday]
    pool = preferred if len(preferred) >= k else eligible  # fall back if not enough

    if len(pool) <= k:
        return pool[:]

    selected = []
    remaining = pool[:]

    while len(selected) < k and remaining:
        rates = [m['chore_rate'] for m in remaining]
        max_rate = max(rates) if max(rates) > 0 else 1.0
        weights = [math.exp(-DECAY * (r / (max_rate + 0.0001))) for r in rates]
        pick = random.choices(remaining, weights=weights, k=1)[0]
        selected.append(pick)
        remaining = [m for m in remaining if m['member_id'] != pick['member_id']]

    return selected


def add_member(name: str):
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        highest_rate = _get_highest_chore_rate(conn)
        cursor.execute("INSERT INTO members (name, score_adjustment) VALUES (%s, %s)", (name, highest_rate))
        conn.commit()
        return {"message": f"Member '{name}' added with starting chore rate of {highest_rate:.2f}."}
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
        cursor.execute("UPDATE members SET is_active = FALSE WHERE member_id = %s", (member_id,))
        conn.commit()
        return {"message": f"Member {member_id} deactivated."}
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
        cursor.execute("SELECT member_id, name FROM members WHERE is_active = TRUE ORDER BY name")
        return cursor.fetchall()
    except Exception as err:
        print(f"Failed to get members: {err}")
        return []
    finally:
        cursor.close()
        conn.close()


def get_absent_members_today():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    try:
        cursor.execute("""
            SELECT m.member_id, m.name FROM members m
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


def swap_assignment(assignment_id: int, new_member_id: int):
    """
    Swaps an existing chore assignment to a different member.
    Reverses the chore record for the original member and assigns it to the new one.
    """
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor(dictionary=True)
    try:
        # Get original assignment
        cursor.execute(
            "SELECT * FROM chore_assignments WHERE assignment_id = %s",
            (assignment_id,)
        )
        assignment = cursor.fetchone()
        if not assignment:
            return {"error": "Assignment not found."}

        # Get new member name for response
        cursor.execute("SELECT name FROM members WHERE member_id = %s", (new_member_id,))
        new_member = cursor.fetchone()
        if not new_member:
            return {"error": "New member not found."}

        # Get old member name
        cursor.execute("SELECT name FROM members WHERE member_id = %s", (assignment['member_id'],))
        old_member = cursor.fetchone()

        # Update assignment to new member
        cursor.execute(
            "UPDATE chore_assignments SET member_id = %s WHERE assignment_id = %s",
            (new_member_id, assignment_id)
        )
        conn.commit()

        return {
            "message": f"Reassigned {assignment['chore_type']} from {old_member['name']} to {new_member['name']}."
        }
    except Exception as err:
        return {"error": f"Failed to swap assignment: {err}"}
    finally:
        cursor.close()
        conn.close()


def mark_late_arrival(member_id: int, action: str, swap_assignment_id: int = None):
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    is_friday = (today.weekday() == 4)
    try:
        cursor.execute(
            "REPLACE INTO attendance (member_id, attendance_date, is_present) VALUES (%s, %s, TRUE)",
            (member_id, today)
        )
        if action == "attendance_only":
            conn.commit()
            return {"message": "Attendance recorded. No chore changes made."}
        elif action == "fill_gap":
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
            cursor.execute(
                "INSERT INTO chore_assignments (member_id, chore_type, assignment_date) VALUES (%s, %s, %s)",
                (member_id, chore_type, today)
            )
            conn.commit()
            return {"message": f"Attendance recorded and assigned to {chore_type}."}
        elif action == "swap_dishes":
            if not swap_assignment_id:
                return {"error": "No assignment ID provided for swap."}
            cursor.execute(
                "SELECT * FROM chore_assignments WHERE assignment_id = %s AND chore_type = 'Washing Dishes'",
                (swap_assignment_id,)
            )
            original = cursor.fetchone()
            if not original:
                return {"error": "Original dish washer assignment not found."}
            cursor.execute("DELETE FROM chore_assignments WHERE assignment_id = %s", (swap_assignment_id,))
            cursor.execute(
                "INSERT INTO chore_assignments (member_id, chore_type, assignment_date) VALUES (%s, 'Washing Dishes', %s)",
                (member_id, today)
            )
            conn.commit()
            return {"message": "Attendance recorded. Dish washing reassigned successfully."}
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
        cursor.execute("SELECT * FROM chore_assignments WHERE assignment_date = %s", (today,))
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

        did_yesterday = _get_members_who_did_chore_yesterday(conn)
        selected = _select_weighted_unique(eligible, chores_to_assign, did_yesterday)

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
                assignments['cooks'].append({
                    'name': row['name'],
                    'assignment_id': row['assignment_id'],
                    'member_id': row['member_id']
                })
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


def get_schedule(days: int = 30):
    """
    Returns a schedule of chore assignments for the last N days.
    Each entry: { date, day_name, cooks: [...], dish_washer: [...] }
    """
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    try:
        cursor.execute("""
            SELECT ca.assignment_date, ca.chore_type, m.name
            FROM chore_assignments ca
            JOIN members m ON ca.member_id = m.member_id
            WHERE ca.assignment_date BETWEEN %s AND %s
            ORDER BY ca.assignment_date DESC
        """, (start_date, today))
        rows = cursor.fetchall()

        # Group by date
        days_map = {}
        for row in rows:
            d = row['assignment_date'].isoformat()
            if d not in days_map:
                days_map[d] = {
                    "date": d,
                    "day_name": row['assignment_date'].strftime("%A, %b %d"),
                    "cooks": [],
                    "dish_washer": []
                }
            if row['chore_type'] == 'Cooking':
                days_map[d]['cooks'].append(row['name'])
            else:
                days_map[d]['dish_washer'].append(row['name'])

        return list(days_map.values())
    finally:
        cursor.close()
        conn.close()


def get_history_summary():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT member_id, name FROM members WHERE is_active = TRUE ORDER BY name")
        members = cursor.fetchall()
        summary = []
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        for member in members:
            mid = member['member_id']
            cursor.execute("SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s", (mid,))
            total_chores = cursor.fetchone()['total']
            cursor.execute("SELECT COUNT(*) as total FROM attendance WHERE member_id = %s AND is_present = TRUE", (mid,))
            days_present = cursor.fetchone()['total']
            chore_rate = round(total_chores / days_present, 3) if days_present > 0 else 0.0
            cursor.execute(
                "SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s AND assignment_date >= %s",
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