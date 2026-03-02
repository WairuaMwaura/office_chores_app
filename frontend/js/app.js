document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    if (path === '/' || path === '/index.html') {
        initIndexPage();
    } else if (path === '/people' || path === '/people.html') {
        initPeoplePage();
    } else if (path === '/history' || path === '/history.html') {
        initHistoryPage();
    }
    setActiveNav();
});

function setActiveNav() {
    const path = window.location.pathname;
    const navLinks = document.querySelectorAll('nav a');
    navLinks.forEach(link => {
        const linkPath = new URL(link.href).pathname;
        if (linkPath === path || (path === '/' && linkPath === '/index.html')) {
            link.classList.add('active');
        }
    });
}

const API_URL = window.location.origin;

function showMessage(type, text) {
    const container = document.getElementById('message-container');
    if (!container) return;
    container.innerHTML = `<div class="message ${type}">${text}</div>`;
}

// --- Index Page Logic ---
async function initIndexPage() {
    const attendanceList = document.getElementById('attendance-list');
    const assignButton = document.getElementById('assign-chores-btn');
    const assignmentsCard = document.getElementById('assignments-card');
    const lateArrivalCard = document.getElementById('late-arrival-card');

    async function loadMembers() {
        try {
            const response = await fetch(`${API_URL}/api/members`);
            const members = await response.json();
            attendanceList.innerHTML = '';
            if (members.length === 0) {
                attendanceList.innerHTML = '<li>Please add members on the "Manage People" page first.</li>';
                assignButton.disabled = true;
            } else {
                members.forEach(member => {
                    const li = document.createElement('li');
                    li.innerHTML = `
                        <input type="checkbox" id="member-${member.member_id}" value="${member.member_id}">
                        <label for="member-${member.member_id}">${member.name}</label>
                    `;
                    attendanceList.appendChild(li);
                });
                assignButton.disabled = false;
            }
        } catch (error) {
            showMessage('error', 'Failed to load members.');
        }
    }

    async function showAssignments(cooks, dishWasher) {
        document.getElementById('cooks-list').textContent = cooks.join(', ') || 'N/A';
        // dish_washer can be array of strings OR array of objects (after late arrival update)
        const dishNames = dishWasher.map(d => typeof d === 'object' ? d.name : d);
        document.getElementById('dishes-list').textContent = dishNames.join(', ') || 'N/A';
        assignmentsCard.style.display = 'block';
        assignButton.disabled = true;
        await loadLateArrivalSection();
    }

    async function loadTodaysAssignments() {
        try {
            const response = await fetch(`${API_URL}/api/chores/today`);
            const assignments = await response.json();
            const cooks = assignments.cooks || [];
            const dishWasher = assignments.dish_washer || [];
            if (cooks.length > 0 || dishWasher.length > 0) {
                await showAssignments(cooks, dishWasher);
            }
        } catch (error) {
            console.error('Could not fetch today\'s assignments:', error);
        }
    }

    assignButton.addEventListener('click', async () => {
        const checkedBoxes = document.querySelectorAll('#attendance-list input[type="checkbox"]:checked');
        const present_ids = Array.from(checkedBoxes).map(cb => parseInt(cb.value));

        try {
            await fetch(`${API_URL}/api/attendance`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ present_ids })
            });
        } catch (error) {
            showMessage('error', 'Failed to mark attendance.');
            return;
        }

        try {
            const response = await fetch(`${API_URL}/api/chores/assign`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) {
                showMessage('warning', result.message || 'An error occurred.');
            } else {
                const { assignments, message } = result;
                await showAssignments(assignments.cooks, assignments.dish_washer);
                showMessage('success', message);
            }
        } catch (error) {
            showMessage('error', 'An unexpected error occurred during assignment.');
        }
    });

    // --- Late Arrival ---
    async function loadLateArrivalSection() {
        try {
            const response = await fetch(`${API_URL}/api/attendance/absent-today`);
            const absentMembers = await response.json();
            const select = document.getElementById('late-member-select');
            select.innerHTML = '<option value="">— Select member —</option>';

            if (absentMembers.length === 0) {
                lateArrivalCard.style.display = 'none';
                return;
            }

            absentMembers.forEach(member => {
                const option = document.createElement('option');
                option.value = member.member_id;
                option.textContent = member.name;
                select.appendChild(option);
            });

            lateArrivalCard.style.display = 'block';
            document.getElementById('late-arrival-options').style.display = 'none';
        } catch (err) {
            console.error('Failed to load absent members:', err);
        }
    }

    document.getElementById('check-late-btn').addEventListener('click', async () => {
        const select = document.getElementById('late-member-select');
        const memberId = parseInt(select.value);
        if (!memberId) {
            showMessage('error', 'Please select a member first.');
            return;
        }

        try {
            const statusRes = await fetch(`${API_URL}/api/chores/status`);
            const status = await statusRes.json();
            const memberName = select.options[select.selectedIndex].text;

            const optionsDiv = document.getElementById('late-arrival-options');
            const contextP = document.getElementById('late-arrival-context');
            const actionsDiv = document.getElementById('late-arrival-actions');
            actionsDiv.innerHTML = '';
            optionsDiv.style.display = 'block';

            // Case 1: Chores not yet assigned — just mark attendance
            if (!status.chores_assigned) {
                contextP.textContent = `Chores haven't been assigned yet. ${memberName} will be included in the next assignment.`;
                addActionButton(actionsDiv, 'Note Attendance Only', 'secondary', async () => {
                    await submitLateArrival(memberId, 'attendance_only');
                });
                return;
            }

            // Case 2: Friday — no dish washer slot, just note attendance
            if (status.is_friday) {
                contextP.textContent = `It's Friday — no dish washer slot. ${memberName} can only be noted as present.`;
                addActionButton(actionsDiv, 'Note Attendance Only', 'secondary', async () => {
                    await submitLateArrival(memberId, 'attendance_only');
                });
                return;
            }

            // Case 3: Open slots (understaffed)
            if (!status.fully_staffed) {
                const missing = !status.cooks_filled ? 'Cook' : 'Dish Washer';
                contextP.textContent = `There's an open ${missing} slot. ${memberName} can fill it.`;
                addActionButton(actionsDiv, `Assign as ${missing}`, 'primary', async () => {
                    await submitLateArrival(memberId, 'fill_gap');
                });
                addActionButton(actionsDiv, 'Just Note Attendance', 'secondary', async () => {
                    await submitLateArrival(memberId, 'attendance_only');
                });
                return;
            }

            // Case 4: Fully staffed — offer swap or attendance only
            const dishWashers = status.dish_washers || [];
            if (dishWashers.length > 0) {
                const dw = dishWashers[0];
                contextP.textContent = `All chores are assigned. ${memberName} can take over dish washing from ${dw.name}, or just be noted as present.`;
                addActionButton(actionsDiv, `Swap: ${memberName} does dishes instead of ${dw.name}`, 'warning', async () => {
                    await submitLateArrival(memberId, 'swap_dishes', dw.assignment_id);
                });
                addActionButton(actionsDiv, 'Just Note Attendance', 'secondary', async () => {
                    await submitLateArrival(memberId, 'attendance_only');
                });
            } else {
                contextP.textContent = `All chores are assigned and no dish washer to swap. ${memberName} will just be noted as present.`;
                addActionButton(actionsDiv, 'Note Attendance Only', 'secondary', async () => {
                    await submitLateArrival(memberId, 'attendance_only');
                });
            }

        } catch (err) {
            showMessage('error', 'Failed to check chore status.');
        }
    });

    function addActionButton(container, label, style, onClick) {
        const btn = document.createElement('button');
        btn.textContent = label;
        btn.className = style;
        btn.style.marginRight = '8px';
        btn.style.marginTop = '8px';
        btn.addEventListener('click', onClick);
        container.appendChild(btn);
    }

    async function submitLateArrival(memberId, action, swapAssignmentId = null) {
        try {
            const payload = { member_id: memberId, action };
            if (swapAssignmentId) payload.swap_assignment_id = swapAssignmentId;

            const response = await fetch(`${API_URL}/api/attendance/late-arrival`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const result = await response.json();

            if (!response.ok) {
                showMessage('error', result.error || 'Failed to process late arrival.');
            } else {
                showMessage('success', result.message);
                // Refresh assignments display and late arrival section
                const assignRes = await fetch(`${API_URL}/api/chores/today`);
                const assignments = await assignRes.json();
                await showAssignments(assignments.cooks || [], assignments.dish_washer || []);
            }
        } catch (err) {
            showMessage('error', 'An unexpected error occurred.');
        }
    }

    loadMembers();
    loadTodaysAssignments();
}

// --- People Page Logic ---
async function initPeoplePage() {
    const memberList = document.getElementById('member-list');
    const addMemberForm = document.getElementById('add-member-form');
    const newMemberNameInput = document.getElementById('new-member-name');

    async function loadMembers() {
        try {
            const response = await fetch(`${API_URL}/api/members`);
            const members = await response.json();
            memberList.innerHTML = '';
            members.forEach(member => {
                const li = document.createElement('li');
                li.innerHTML = `
                    <label>${member.name}</label>
                    <button class="danger remove-btn" data-id="${member.member_id}">Remove</button>
                `;
                memberList.appendChild(li);
            });
        } catch (error) {
            showMessage('error', 'Failed to load members.');
        }
    }

    addMemberForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = newMemberNameInput.value.trim();
        if (!name) return;
        try {
            const formData = new FormData();
            formData.append('name', name);
            const response = await fetch(`${API_URL}/api/members/add`, {
                method: 'POST',
                body: formData
            });
            if (response.ok) {
                newMemberNameInput.value = '';
                loadMembers();
                showMessage('success', `Member "${name}" added.`);
            } else {
                const result = await response.json();
                showMessage('error', result.error || 'Failed to add member.');
            }
        } catch (error) {
            showMessage('error', 'An unexpected error occurred.');
        }
    });

    memberList.addEventListener('click', async (e) => {
        if (e.target.classList.contains('remove-btn')) {
            const memberId = e.target.dataset.id;
            const memberName = e.target.previousElementSibling.textContent;
            if (confirm(`Are you sure you want to remove ${memberName}?`)) {
                try {
                    const formData = new FormData();
                    formData.append('member_id', memberId);
                    const response = await fetch(`${API_URL}/api/members/remove`, {
                        method: 'POST',
                        body: formData
                    });
                    if (response.ok) {
                        loadMembers();
                        showMessage('success', `${memberName} was removed.`);
                    } else {
                        const result = await response.json();
                        showMessage('error', result.error || 'Failed to remove member.');
                    }
                } catch (error) {
                    showMessage('error', 'An unexpected error occurred.');
                }
            }
        }
    });

    loadMembers();
}

// --- History Page Logic ---
async function initHistoryPage() {
    const historyTableBody = document.getElementById('history-table-body');
    try {
        const response = await fetch(`${API_URL}/api/history/summary`);
        const summary = await response.json();
        if (summary.length === 0) {
            historyTableBody.innerHTML = '<tr><td colspan="5">No history data available. Add members and assign chores.</td></tr>';
            return;
        }
        summary.forEach(item => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${item.name}</td>
                <td>${item.chores_this_week}</td>
                <td>${item.total_chores}</td>
                <td>${item.days_present}</td>
                <td>${item.chore_rate}</td>
            `;
            historyTableBody.appendChild(row);
        });
    } catch (error) {
        showMessage('error', 'Failed to load history data.');
    }
}