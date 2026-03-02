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
        // Normalize href to match pathname for comparison
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

    async function loadMembers() {
        try {
            const response = await fetch(`${API_URL}/api/members`);
            const members = await response.json();
            attendanceList.innerHTML = ''; // Clear previous list
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

    async function loadTodaysAssignments() {
        try {
            const response = await fetch(`${API_URL}/api/chores/today`);
            const assignments = await response.json();
            const cooks = assignments.cooks || [];
            const dishWasher = assignments.dish_washer || [];

            if (cooks.length > 0 || dishWasher.length > 0) {
                document.getElementById('cooks-list').textContent = cooks.join(', ') || 'N/A';
                document.getElementById('dishes-list').textContent = dishWasher.join(', ') || 'N/A';
                showMessage('success', 'Chores for today have already been assigned.');
                assignButton.disabled = true; // Disable if already assigned
            }
        } catch (error) {
            console.error('Could not fetch today\'s assignments:', error);
        }
    }

    assignButton.addEventListener('click', async () => {
        const checkedBoxes = document.querySelectorAll('#attendance-list input[type="checkbox"]:checked');
        const present_ids = Array.from(checkedBoxes).map(cb => parseInt(cb.value));

        // Step 1: Mark attendance
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

        // Step 2: Try to assign chores
        try {
            const response = await fetch(`${API_URL}/api/chores/assign`, { method: 'POST' });
            const result = await response.json();

            if (!response.ok) {
                showMessage('warning', result.message || 'An error occurred.');
            } else {
                const { assignments, message } = result;
                document.getElementById('cooks-list').textContent = assignments.cooks.join(', ');
                document.getElementById('dishes-list').textContent = assignments.dish_washer.join(', ');
                showMessage('success', message);
                assignButton.disabled = true; // Disable after successful assignment
            }
        } catch (error) {
            showMessage('error', 'An unexpected error occurred during assignment.');
        }
    });

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
            historyTableBody.innerHTML = '<tr><td colspan="5">No history data available.</td></tr>';
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