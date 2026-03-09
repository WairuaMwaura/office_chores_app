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


def _get_week_bounds() -> tuple:
    """Returns (start_of_week Monday, today)."""
    today = date.today()
    return today - timedelta(days=today.weekday()), today


def _get_alltime_chore_rate(member_id: int, conn) -> float:
    """Total chores / total days present (all-time)."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s", (member_id,))
        total_chores = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE member_id = %s AND is_present = TRUE", (member_id,))
        total_days = cursor.fetchone()[0]
        return total_chores / total_days if total_days > 0 else 0.0
    finally:
        cursor.close()


def _get_weekly_chore_rate(member_id: int, conn) -> float:
    """Chores this calendar week / days attended this calendar week."""
    start_of_week, today = _get_week_bounds()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s AND assignment_date BETWEEN %s AND %s",
            (member_id, start_of_week, today)
        )
        weekly_chores = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM attendance WHERE member_id = %s AND is_present = TRUE AND attendance_date BETWEEN %s AND %s",
            (member_id, start_of_week, today)
        )
        weekly_days = cursor.fetchone()[0]
        return weekly_chores / weekly_days if weekly_days > 0 else 0.0
    finally:
        cursor.close()


def _get_weekly_chore_count(member_id: int, conn) -> int:
    """Raw count of chores done this calendar week."""
    start_of_week, today = _get_week_bounds()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM chore_assignments WHERE member_id = %s AND assignment_date BETWEEN %s AND %s",
            (member_id, start_of_week, today)
        )
        return cursor.fetchone()[0]
    finally:
        cursor.close()


def _get_combined_score(member_id: int, conn, score_adjustment: float = 0.0) -> float:
    """
    Combined fairness score: 70% weekly rate + 30% all-time rate.
    score_adjustment is used as a floor for new members.
    Lower = higher priority.
    """
    weekly_rate = _get_weekly_chore_rate(member_id, conn)
    alltime_rate = _get_alltime_chore_rate(member_id, conn)
    alltime_rate = max(alltime_rate, score_adjustment)
    weekly_rate = max(weekly_rate, score_adjustment)
    return 0.7 * weekly_rate + 0.3 * alltime_rate


def _get_members_who_did_chore_yesterday(conn) -> set:
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


def _get_highest_combined_score(conn) -> float:
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT member_id, score_adjustment FROM members WHERE is_active = TRUE")
        members = cursor.fetchall()
        if not members:
            return 0.0
        scores = [_get_combined_score(m['member_id'], conn, m['score_adjustment']) for m in members]
        return max(scores)
    finally:
        cursor.close()


def _weighted_pick_unique(pool: list, k: int, score_key: str = 'combined_score') -> list:
    """
    Picks k unique members from pool using exponential inverse weighting
    on the given score_key. Lower score = higher chance of selection.
    """
    DECAY = 4.0
    if len(pool) <= k:
        return pool[:]

    selected = []
    remaining = pool[:]

    while len(selected) < k and remaining:
        scores = [m[score_key] for m in remaining]
        max_score = max(scores) if max(scores) > 0 else 1.0
        weights = [math.exp(-DECAY * (s / (max_score + 0.0001))) for s in scores]
        pick = random.choices(remaining, weights=weights, k=1)[0]
        selected.append(pick)
        remaining = [m for m in remaining if m['member_id'] != pick['member_id']]

    return selected


def _select_fair(eligible: list, k: int, did_yesterday: set) -> list:
    """
    Strict weekly queue with combined score tiebreaker:

    1. Split eligible into:
       - Group A: did 0 chores this week (strict priority)
       - Group B: did 1+ chores this week (overflow only)

    2. Within each group, apply yesterday-blocking first:
       - Prefer members who did NOT do a chore yesterday
       - Fall back to full group only if not enough unblocked members

    3. Fill slots from Group A first using all-time rate as tiebreaker.
       If Group A can't fill all slots, fill remaining from Group B
       using combined score (70% weekly + 30% all-time) as tiebreaker.
    """
    group_a = [m for m in eligible if m['weekly_chore_count'] == 0]
    group_b = [m for m in eligible if m['weekly_chore_count'] > 0]

    def apply_yesterday_block(group):
        preferred = [m for m in group if m['member_id'] not in did_yesterday]
        return preferred if len(preferred) > 0 else group

    selected = []

    # Fill from Group A first
    slots_remaining = k
    if group_a:
        pool_a = apply_yesterday_block(group_a)
        # Use all-time rate as tiebreaker within Group A
        picks_a = _weighted_pick_unique(pool_a, slots_remaining, score_key='alltime_rate')
        selected.extend(picks_a)
        slots_remaining -= len(picks_a)

    # Fill remaining slots from Group B if needed
    if slots_remaining > 0 and group_b:
        # Exclude already selected members
        selected_ids = {m['member_id'] for m in selected}
        pool_b = [m for m in group_b if m['member_id'] not in selected_ids]
        pool_b = apply_yesterday_block(pool_b)
        picks_b = _weighted_pick_unique(pool_b, slots_remaining, score_key='combined_score')
        selected.extend(picks_b)

    return selected


def get_all_members_with_scores():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT member_id, name, score_adjustment FROM members WHERE is_active = TRUE")
        members = cursor.fetchall()
        for m in members:
            m['combined_score'] = _get_combined_score(m['member_id'], conn, m['score_adjustment'])
            m['weekly_rate'] = _get_weekly_chore_rate(m['member_id'], conn)
            m['alltime_rate'] = _get_alltime_chore_rate(m['member_id'], conn)
            m['weekly_chore_count'] = _get_weekly_chore_count(m['member_id'], conn)
        return members
    finally:
        cursor.close()
        conn.close()


def add_member(name: str):
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor()
    try:
        highest = _get_highest_combined_score(conn)
        cursor.execute("INSERT INTO members (name, score_adjustment) VALUES (%s, %s)", (name, highest))
        conn.commit()
        return {"message": f"Member '{name}' added with starting score of {highest:.2f}."}
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
    conn = get_db_connection()
    if not conn:
        return {"error": "Database connection failed."}
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM chore_assignments WHERE assignment_id = %s", (assignment_id,))
        assignment = cursor.fetchone()
        if not assignment:
            return {"error": "Assignment not found."}
        cursor.execute("SELECT name FROM members WHERE member_id = %s", (new_member_id,))
        new_member = cursor.fetchone()
        if not new_member:
            return {"error": "New member not found."}
        cursor.execute("SELECT name FROM members WHERE member_id = %s", (assignment['member_id'],))
        old_member = cursor.fetchone()
        cursor.execute(
            "UPDATE chore_assignments SET member_id = %s WHERE assignment_id = %s",
            (new_member_id, assignment_id)
        )
        conn.commit()
        return {"message": f"Reassigned {assignment['chore_type']} from {old_member['name']} to {new_member['name']}."}
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
            chore_type = 'Cooking' if len(status['cooks']) < 2 else 'Washing Dishes'
            if chore_type == 'Washing Dishes' and is_friday:
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
    """
    Assigns chores using strict weekly queue + combined score tiebreaker:
    - Group A (0 chores this week) always picked before Group B (1+ chores this week)
    - Within groups, yesterday-blocking applied first
    - All-time rate used as tiebreaker within Group A
    - Combined score (70% weekly + 30% all-time) used for Group B
    - Friday: 2 cooks only, min 2 present
    - Other days: 2 cooks + 1 dish washer, min 3 present
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

        # Build eligible list with all score data
        cursor.execute(
            "SELECT member_id, name, score_adjustment FROM members WHERE is_active = TRUE"
        )
        all_active = cursor.fetchall()
        eligible = []
        for m in all_active:
            if m['member_id'] not in present_today:
                continue
            eligible.append({
                'member_id': m['member_id'],
                'name': m['name'],
                'alltime_rate': _get_alltime_chore_rate(m['member_id'], conn),
                'combined_score': _get_combined_score(m['member_id'], conn, m['score_adjustment']),
                'weekly_chore_count': _get_weekly_chore_count(m['member_id'], conn),
            })

        if len(eligible) < chores_to_assign:
            return None, "Not enough eligible members to assign chores."

        did_yesterday = _get_members_who_did_chore_yesterday(conn)
        selected = _select_fair(eligible, chores_to_assign, did_yesterday)

        if len(selected) < chores_to_assign:
            return None, "Could not select enough members. Please check attendance."

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
            entry = {'name': row['name'], 'assignment_id': row['assignment_id'], 'member_id': row['member_id']}
            if row['chore_type'] == 'Cooking':
                assignments['cooks'].append(entry)
            else:
                assignments['dish_washer'].append(entry)
        return assignments
    finally:
        cursor.close()
        conn.close()


def get_schedule(days: int = 30):
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
    start_of_week, today = _get_week_bounds()
    try:
        cursor.execute("SELECT member_id, name, score_adjustment FROM members WHERE is_active = TRUE ORDER BY name")
        members = cursor.fetchall()
        summary = []
        for member in members:
            mid = member['member_id']

            cursor.execute("SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s", (mid,))
            total_chores = cursor.fetchone()['total']

            cursor.execute("SELECT COUNT(*) as total FROM attendance WHERE member_id = %s AND is_present = TRUE", (mid,))
            days_present = cursor.fetchone()['total']

            cursor.execute(
                "SELECT COUNT(*) as total FROM chore_assignments WHERE member_id = %s AND assignment_date BETWEEN %s AND %s",
                (mid, start_of_week, today)
            )
            chores_this_week = cursor.fetchone()['total']

            cursor.execute(
                "SELECT COUNT(*) as total FROM attendance WHERE member_id = %s AND is_present = TRUE AND attendance_date BETWEEN %s AND %s",
                (mid, start_of_week, today)
            )
            days_present_this_week = cursor.fetchone()['total']

            alltime_rate = round(total_chores / days_present, 3) if days_present > 0 else 0.0
            weekly_rate = round(chores_this_week / days_present_this_week, 3) if days_present_this_week > 0 else 0.0
            combined = round(0.7 * weekly_rate + 0.3 * alltime_rate, 3)

            summary.append({
                "name": member['name'],
                "chores_this_week": chores_this_week,
                "days_present_this_week": days_present_this_week,
                "weekly_rate": weekly_rate,
                "total_chores": total_chores,
                "days_present": days_present,
                "alltime_rate": alltime_rate,
                "combined_score": combined,
            })
        return summary
    finally:
        cursor.close()
        conn.close()