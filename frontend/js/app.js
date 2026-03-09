document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    if (path === '/' || path === '/index.html') {
        initIndexPage();
    } else if (path === '/people' || path === '/people.html') {
        initPeoplePage();
    } else if (path === '/history' || path === '/history.html') {
        initHistoryPage();
    } else if (path === '/schedule' || path === '/schedule.html') {
        initSchedulePage();
    }
    setActiveNav();
});

function setActiveNav() {
    const path = window.location.pathname;
    document.querySelectorAll('nav a').forEach(link => {
        if (new URL(link.href).pathname === path) link.classList.add('active');
    });
}

const API_URL = window.location.origin;

function showMessage(type, text) {
    const container = document.getElementById('message-container');
    if (!container) return;
    container.innerHTML = `<div class="message ${type}">${text}</div>`;
}

// ─────────────────────────────────────────────
// INDEX PAGE
// ─────────────────────────────────────────────
async function initIndexPage() {
    const attendanceList = document.getElementById('attendance-list');
    const assignButton = document.getElementById('assign-chores-btn');
    const lateArrivalCard = document.getElementById('late-arrival-card');

    async function loadMembers() {
        try {
            const members = await fetchJSON('/api/members');
            attendanceList.innerHTML = '';
            if (members.length === 0) {
                attendanceList.innerHTML = '<li>Please add members on the "Manage People" page first.</li>';
                assignButton.disabled = true;
            } else {
                members.forEach(member => {
                    const li = document.createElement('li');
                    li.innerHTML = `
                        <input type="checkbox" id="member-${member.member_id}" value="${member.member_id}">
                        <label for="member-${member.member_id}">${member.name}</label>`;
                    attendanceList.appendChild(li);
                });
            }
        } catch {
            showMessage('error', 'Failed to load members.');
        }
    }

    function renderAssignments(cooks, dishWasher) {
        const cooksContainer = document.getElementById('cooks-list-container');
        const dishesContainer = document.getElementById('dishes-list-container');
        const cooksPlaceholder = document.getElementById('cooks-placeholder');
        const dishesPlaceholder = document.getElementById('dishes-placeholder');

        cooksContainer.innerHTML = '';
        dishesContainer.innerHTML = '';

        if (cooks.length > 0) {
            cooksPlaceholder.style.display = 'none';
            cooks.forEach(c => cooksContainer.appendChild(assignmentItem(c)));
        } else {
            cooksPlaceholder.style.display = 'block';
        }

        if (dishWasher.length > 0) {
            dishesPlaceholder.style.display = 'none';
            dishWasher.forEach(d => {
                const nameStr = typeof d === 'object' ? d.name : d;
                if (nameStr === 'N/A (Friday)') {
                    dishesContainer.innerHTML = `<p style="font-size:1.1rem;font-weight:600;">N/A (Friday)</p>`;
                } else {
                    dishesContainer.appendChild(assignmentItem(d));
                }
            });
        } else {
            dishesPlaceholder.style.display = 'block';
        }
    }

    function assignmentItem(person) {
        const p = typeof person === 'object' ? person : { name: person, assignment_id: null };
        const div = document.createElement('div');
        div.className = 'assignment-item';
        div.innerHTML = `
            <span class="assignment-name">${p.name}</span>
            ${p.assignment_id
                ? `<button class="swap-btn small-btn" data-assignment-id="${p.assignment_id}" data-name="${p.name}">↔ Swap</button>`
                : ''}`;
        return div;
    }

    // ── Swap modal ──
    let activeSwapAssignmentId = null;

    document.addEventListener('click', async (e) => {
        if (!e.target.classList.contains('swap-btn')) return;
        activeSwapAssignmentId = parseInt(e.target.dataset.assignmentId);
        const currentName = e.target.dataset.name;
        document.getElementById('swap-modal-title').textContent = `Replace ${currentName}`;
        document.getElementById('swap-modal-context').textContent =
            `Select who should take over this chore from ${currentName}.`;

        const members = await fetchJSON('/api/members');
        const select = document.getElementById('swap-member-select');
        select.innerHTML = '<option value="">— Select replacement —</option>';
        members.forEach(m => {
            if (m.name !== currentName) {
                const opt = document.createElement('option');
                opt.value = m.member_id;
                opt.textContent = m.name;
                select.appendChild(opt);
            }
        });
        document.getElementById('swap-modal').style.display = 'flex';
    });

    document.getElementById('swap-cancel-btn').addEventListener('click', () => {
        document.getElementById('swap-modal').style.display = 'none';
        activeSwapAssignmentId = null;
    });

    document.getElementById('swap-modal').addEventListener('click', (e) => {
        if (e.target.id === 'swap-modal') document.getElementById('swap-modal').style.display = 'none';
    });

    document.getElementById('swap-confirm-btn').addEventListener('click', async () => {
        const newMemberId = parseInt(document.getElementById('swap-member-select').value);
        if (!newMemberId) { showMessage('error', 'Please select a replacement.'); return; }
        try {
            const result = await postJSON('/api/chores/swap', {
                assignment_id: activeSwapAssignmentId,
                new_member_id: newMemberId
            });
            document.getElementById('swap-modal').style.display = 'none';
            activeSwapAssignmentId = null;
            showMessage('success', result.message);
            await refreshAssignments();
        } catch (err) {
            showMessage('error', err.message || 'Failed to swap assignment.');
        }
    });

    async function refreshAssignments() {
        const assignments = await fetchJSON('/api/chores/today');
        renderAssignments(assignments.cooks || [], assignments.dish_washer || []);
        await loadLateArrivalSection();
    }

    async function loadTodaysAssignments() {
        try {
            const assignments = await fetchJSON('/api/chores/today');
            const cooks = assignments.cooks || [];
            const dishWasher = assignments.dish_washer || [];
            if (cooks.length > 0 || dishWasher.length > 0) {
                renderAssignments(cooks, dishWasher);
                assignButton.disabled = true;
                await loadLateArrivalSection();
            }
        } catch {
            console.error('Could not fetch today\'s assignments.');
        }
    }

    assignButton.addEventListener('click', async () => {
        const checkedBoxes = document.querySelectorAll('#attendance-list input[type="checkbox"]:checked');
        const present_ids = Array.from(checkedBoxes).map(cb => parseInt(cb.value));
        try {
            await postJSON('/api/attendance', { present_ids });
        } catch {
            showMessage('error', 'Failed to mark attendance.');
            return;
        }
        try {
            const result = await postJSON('/api/chores/assign', {});
            renderAssignments(result.assignments.cooks, result.assignments.dish_washer);
            assignButton.disabled = true;
            showMessage('success', result.message);
            await loadLateArrivalSection();
        } catch (err) {
            showMessage('warning', err.message || 'An error occurred.');
        }
    });

    // ── Late Arrival ──
    async function loadLateArrivalSection() {
        try {
            const absentMembers = await fetchJSON('/api/attendance/absent-today');
            const select = document.getElementById('late-member-select');
            select.innerHTML = '<option value="">— Select member —</option>';
            if (absentMembers.length === 0) {
                lateArrivalCard.style.display = 'none';
                return;
            }
            absentMembers.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.member_id;
                opt.textContent = m.name;
                select.appendChild(opt);
            });
            document.getElementById('late-arrival-options').style.display = 'none';
            lateArrivalCard.style.display = 'block';
        } catch {
            console.error('Failed to load absent members.');
        }
    }

    document.getElementById('check-late-btn').addEventListener('click', async () => {
        const select = document.getElementById('late-member-select');
        const memberId = parseInt(select.value);
        if (!memberId) { showMessage('error', 'Please select a member.'); return; }

        const status = await fetchJSON('/api/chores/status');
        const memberName = select.options[select.selectedIndex].text;
        const optionsDiv = document.getElementById('late-arrival-options');
        const contextP = document.getElementById('late-arrival-context');
        const actionsDiv = document.getElementById('late-arrival-actions');
        actionsDiv.innerHTML = '';
        optionsDiv.style.display = 'block';

        if (!status.chores_assigned) {
            contextP.textContent = `Chores haven't been assigned yet. ${memberName} will be included when chores are assigned.`;
            addBtn(actionsDiv, 'Note Attendance Only', '', () => submitLate(memberId, 'attendance_only'));
        } else if (status.is_friday) {
            contextP.textContent = `It's Friday — no dish washer slot. ${memberName} can only be noted as present.`;
            addBtn(actionsDiv, 'Note Attendance Only', '', () => submitLate(memberId, 'attendance_only'));
        } else if (!status.fully_staffed) {
            const missing = !status.cooks_filled ? 'Cook' : 'Dish Washer';
            contextP.textContent = `There's an open ${missing} slot. ${memberName} can fill it.`;
            addBtn(actionsDiv, `Assign as ${missing}`, '', () => submitLate(memberId, 'fill_gap'));
            addBtn(actionsDiv, 'Just Note Attendance', 'secondary-btn', () => submitLate(memberId, 'attendance_only'));
        } else {
            const dws = status.dish_washers || [];
            if (dws.length > 0) {
                const dw = dws[0];
                contextP.textContent = `All chores assigned. ${memberName} can take over dish washing from ${dw.name}, or just be noted as present.`;
                addBtn(actionsDiv, `${memberName} does dishes (swap with ${dw.name})`, '', () => submitLate(memberId, 'swap_dishes', dw.assignment_id));
                addBtn(actionsDiv, 'Just Note Attendance', 'secondary-btn', () => submitLate(memberId, 'attendance_only'));
            } else {
                contextP.textContent = `All chores are assigned. ${memberName} will just be noted as present.`;
                addBtn(actionsDiv, 'Note Attendance Only', '', () => submitLate(memberId, 'attendance_only'));
            }
        }
    });

    function addBtn(container, label, cls, onClick) {
        const btn = document.createElement('button');
        btn.textContent = label;
        if (cls) btn.classList.add(cls);
        btn.addEventListener('click', onClick);
        container.appendChild(btn);
    }

    async function submitLate(memberId, action, swapId = null) {
        try {
            const payload = { member_id: memberId, action };
            if (swapId) payload.swap_assignment_id = swapId;
            const result = await postJSON('/api/attendance/late-arrival', payload);
            showMessage('success', result.message);
            await refreshAssignments();
        } catch (err) {
            showMessage('error', err.message || 'Failed to process late arrival.');
        }
    }

    loadMembers();
    loadTodaysAssignments();
}

// ─────────────────────────────────────────────
// PEOPLE PAGE
// ─────────────────────────────────────────────
async function initPeoplePage() {
    const memberList = document.getElementById('member-list');
    const addMemberForm = document.getElementById('add-member-form');
    const newMemberNameInput = document.getElementById('new-member-name');

    async function loadMembers() {
        try {
            const members = await fetchJSON('/api/members');
            memberList.innerHTML = '';
            members.forEach(member => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <label>${member.name}</label>
                    <button class="danger remove-btn" data-id="${member.member_id}">Remove</button>`;
                memberList.appendChild(li);
            });
        } catch {
            showMessage('error', 'Failed to load members.');
        }
    }

    addMemberForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = newMemberNameInput.value.trim();
        if (!name) return;
        const formData = new FormData();
        formData.append('name', name);
        const response = await fetch(`${API_URL}/api/members/add`, { method: 'POST', body: formData });
        const result = await response.json();
        if (response.ok) {
            newMemberNameInput.value = '';
            loadMembers();
            showMessage('success', `Member "${name}" added.`);
        } else {
            showMessage('error', result.error || 'Failed to add member.');
        }
    });

    memberList.addEventListener('click', async (e) => {
        if (!e.target.classList.contains('remove-btn')) return;
        const memberId = e.target.dataset.id;
        const memberName = e.target.previousElementSibling.textContent;
        if (!confirm(`Are you sure you want to remove ${memberName}?`)) return;
        const formData = new FormData();
        formData.append('member_id', memberId);
        const response = await fetch(`${API_URL}/api/members/remove`, { method: 'POST', body: formData });
        const result = await response.json();
        if (response.ok) {
            loadMembers();
            showMessage('success', `${memberName} was removed.`);
        } else {
            showMessage('error', result.error || 'Failed to remove member.');
        }
    });

    loadMembers();
}

// ─────────────────────────────────────────────
// HISTORY PAGE
// ─────────────────────────────────────────────
async function initHistoryPage() {
    const tbody = document.getElementById('history-table-body');
    try {
        const summary = await fetchJSON('/api/history/summary');
        if (summary.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8">No history data available.</td></tr>';
            return;
        }
        // Sort by combined score ascending so highest priority is at top
        summary.sort((a, b) => a.combined_score - b.combined_score);
        summary.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${item.name}</td>
                <td>${item.chores_this_week}</td>
                <td>${item.days_present_this_week}</td>
                <td>${item.weekly_rate}</td>
                <td>${item.total_chores}</td>
                <td>${item.days_present}</td>
                <td>${item.alltime_rate}</td>
                <td><strong>${item.combined_score}</strong></td>`;
            tbody.appendChild(row);
        });
    } catch {
        showMessage('error', 'Failed to load history data.');
    }
}

// ─────────────────────────────────────────────
// SCHEDULE PAGE
// ─────────────────────────────────────────────
async function initSchedulePage() {
    let scheduleData = [];
    try {
        scheduleData = await fetchJSON('/api/schedule?days=30');
    } catch {
        showMessage('error', 'Failed to load schedule.');
        return;
    }

    if (scheduleData.length === 0) {
        document.getElementById('schedule-table-body').innerHTML =
            '<tr><td colspan="3">No chore data in the last 30 days.</td></tr>';
        return;
    }

    renderTableView(scheduleData);
    renderGridView(scheduleData);

    document.getElementById('view-table-btn').addEventListener('click', () => {
        document.getElementById('schedule-table-view').style.display = 'block';
        document.getElementById('schedule-grid-view').style.display = 'none';
        document.getElementById('view-table-btn').classList.add('active');
        document.getElementById('view-grid-btn').classList.remove('active');
    });

    document.getElementById('view-grid-btn').addEventListener('click', () => {
        document.getElementById('schedule-table-view').style.display = 'none';
        document.getElementById('schedule-grid-view').style.display = 'block';
        document.getElementById('view-grid-btn').classList.add('active');
        document.getElementById('view-table-btn').classList.remove('active');
    });
}

function renderTableView(data) {
    const tbody = document.getElementById('schedule-table-body');
    tbody.innerHTML = '';
    data.forEach(day => {
        const row = document.createElement('tr');
        const dishText = day.dish_washer.length > 0 ? day.dish_washer.join(', ') : 'N/A (Friday)';
        row.innerHTML = `
            <td>${day.day_name}</td>
            <td>${day.cooks.join(', ') || '—'}</td>
            <td>${dishText}</td>`;
        tbody.appendChild(row);
    });
}

function renderGridView(data) {
    const memberSet = new Set();
    data.forEach(day => {
        day.cooks.forEach(n => memberSet.add(n));
        day.dish_washer.forEach(n => memberSet.add(n));
    });
    const members = Array.from(memberSet).sort();
    const grid = document.getElementById('schedule-grid');
    grid.innerHTML = '';

    const headerRow = document.createElement('div');
    headerRow.className = 'grid-row grid-header';
    headerRow.innerHTML = `<div class="grid-cell grid-label">Member</div>`;
    data.forEach(day => {
        const cell = document.createElement('div');
        cell.className = 'grid-cell grid-date';
        cell.textContent = day.day_name.split(',')[0].slice(0, 3) + ' ' + day.date.slice(8);
        headerRow.appendChild(cell);
    });
    grid.appendChild(headerRow);

    members.forEach(member => {
        const row = document.createElement('div');
        row.className = 'grid-row';
        const label = document.createElement('div');
        label.className = 'grid-cell grid-label';
        label.textContent = member;
        row.appendChild(label);

        data.forEach(day => {
            const cell = document.createElement('div');
            cell.className = 'grid-cell';
            if (day.cooks.includes(member)) {
                cell.className += ' grid-cook';
                cell.textContent = '🍳';
                cell.title = 'Cooking';
            } else if (day.dish_washer.includes(member)) {
                cell.className += ' grid-dish';
                cell.textContent = '💧';
                cell.title = 'Washing Dishes';
            }
            row.appendChild(cell);
        });
        grid.appendChild(row);
    });
}

// ─────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────
async function fetchJSON(path) {
    const res = await fetch(`${API_URL}${path}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.error || 'Request failed');
    return data;
}

async function postJSON(path, body) {
    const res = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || data.error || 'Request failed');
    return data;
}