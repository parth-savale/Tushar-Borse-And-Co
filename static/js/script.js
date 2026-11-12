// Global variables
let currentUser = null;
let allClients = [];
let clientYearWiseData = null;
let clientYearWiseError = '';
let allStaff = [];
let allInvoices = [];
let allTasks = [];
let allRemarks = [];
let currentReviewInvoice = null;
let pendingInvoiceDeleteId = null;
let reportSummaryRequestId = 0;
let reportRemarksRequestId = 0;
let referralReportRequestId = 0;
let adminNotes = [];
let adminNotesLoaded = false;
let selectedAdminNoteId = null;
let adminNoteSaveTimer = null;
let adminNoteSavePromise = Promise.resolve();
let adminNoteEditVersion = 0;
let adminNoteHasUnsavedChanges = false;
let adminProfileCsrfToken = '';
let savedAdminProfile = null;

// DOM Elements
const loginScreen = document.getElementById('loginScreen');
const dashboard = document.getElementById('dashboard');
const loginForm = document.getElementById('loginForm');
const userTypeInput = document.getElementById('user_type');
const userRole = document.getElementById('userRole');
const userName = document.getElementById('userName');
const logoutBtn = document.getElementById('logoutBtn');
const statsContainer = document.getElementById('statsContainer');
const tabs = document.querySelectorAll('.tab');
const tabContents = document.querySelectorAll('.tab-content');
const addClientBtn = document.getElementById('addClientBtn');
const addClientModal = document.getElementById('addClientModal');
const closeModalBtns = document.querySelectorAll('.close, .cancel-btn');
const clientForm = document.getElementById('clientForm');
const clientsTableBody = document.getElementById('clientsTableBody');
const clientFinancialYearSelect = document.getElementById('clientFinancialYear');
const clientYearCount = document.getElementById('clientYearCount');
const createInvoiceBtn = document.getElementById('createInvoiceBtn');
const invoiceModal = document.getElementById('invoiceModal');
const invoiceForm = document.getElementById('invoiceForm');
const invoiceClientSelect = document.getElementById('invoiceClient');
const invoiceSearch = document.getElementById('searchInvoice');
const reportFinancialYearSelect = document.getElementById('reportFinancialYear');
const exportReportPdfBtn = document.getElementById('exportReportPdfBtn');
const exportReportExcelBtn = document.getElementById('exportReportExcelBtn');
const referrerSearch = document.getElementById('referrerSearch');
const referrerClientSelect = document.getElementById('referrerClient');
const referralFinancialYearSelect = document.getElementById('referralFinancialYear');
const referralClientSearch = document.getElementById('referralClientSearch');
const exportReferralPdfBtn = document.getElementById('exportReferralPdfBtn');
const exportReferralExcelBtn = document.getElementById('exportReferralExcelBtn');
const staffModal = document.getElementById('staffModal');
const staffForm = document.getElementById('staffForm');
const assignStaffSelect = document.getElementById('assignStaff');
const assignTaskBtn = document.getElementById('assignTaskBtn');
const taskModal = document.getElementById('taskModal');
const taskForm = document.getElementById('taskForm');
const remarkModal = document.getElementById('remarkModal');
const remarkForm = document.getElementById('remarkForm');

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    // Check if user is already logged in
    checkLoginStatus();
    
    // Setup event listeners
    setupEventListeners();
});

// Setup all event listeners
function setupEventListeners() {
    // Login type selection
    document.querySelectorAll('.login-option').forEach(option => {
        option.addEventListener('click', function() {
            document.querySelectorAll('.login-option').forEach(opt => opt.classList.remove('active'));
            this.classList.add('active');
            userTypeInput.value = this.dataset.type;
        });
    });
    
    // Login form submission
    loginForm.addEventListener('submit', handleLogin);
    
    // Logout button
    logoutBtn.addEventListener('click', handleLogout);
    
    // Tab navigation
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabId = tab.dataset.tab;
            if (tabId === 'adminProfile' && currentUser?.role !== 'admin') return;
            switchTab(tabId);
            closeMobileNavigation();
        });
    });

    document.getElementById('adminProfileForm').addEventListener('submit', saveAdminProfile);
    document.getElementById('cancelAdminProfileBtn').addEventListener('click', restoreAdminProfile);
    document.getElementById('adminPasswordForm').addEventListener('submit', changeAdminPassword);
    document.getElementById('changeAdminPictureBtn').addEventListener('click', () => {
        document.getElementById('adminProfilePictureInput').click();
    });
    document.getElementById('adminProfilePictureInput').addEventListener('change', uploadAdminPicture);
    document.getElementById('removeAdminPictureBtn').addEventListener('click', removeAdminPicture);

    const mobileNavToggle = document.getElementById('mobileNavToggle');
    const mobileNavClose = document.getElementById('mobileNavClose');
    const sidebarCollapseToggle = document.getElementById('sidebarCollapseToggle');

    mobileNavToggle.addEventListener('click', () => {
        const isOpen = dashboard.classList.toggle('mobile-nav-open');
        mobileNavToggle.setAttribute('aria-expanded', String(isOpen));
        mobileNavToggle.setAttribute('aria-label', isOpen ? 'Close workspace navigation' : 'Open workspace navigation');
    });
    mobileNavClose.addEventListener('click', closeMobileNavigation);

    sidebarCollapseToggle.addEventListener('click', () => {
        const isCollapsed = dashboard.classList.toggle('sidebar-collapsed');
        sidebarCollapseToggle.setAttribute('aria-expanded', String(!isCollapsed));
        sidebarCollapseToggle.setAttribute('aria-label', isCollapsed ? 'Expand workspace sidebar' : 'Collapse workspace sidebar');
    });

    dashboard.addEventListener('click', event => {
        if (event.target === dashboard && dashboard.classList.contains('mobile-nav-open')) {
            closeMobileNavigation();
        }
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeMobileNavigation();
    });
    
    // Add client button
    addClientBtn.addEventListener('click', () => {
        resetClientForm();
        populateReferrerOptions();
        openModal(addClientModal);
        loadStaffForAssignment();
    });

    document.getElementById('panNumber').addEventListener('input', event => {
        event.target.value = event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10);
    });
    document.getElementById('clientPhone').addEventListener('input', event => {
        event.target.value = event.target.value.replace(/\D/g, '').slice(0, 10);
    });
    referrerSearch.addEventListener('input', () => populateReferrerOptions(referrerClientSelect.value));
    document.getElementById('searchClient').addEventListener('input', () => renderClientsTable(allClients));
    clientFinancialYearSelect.addEventListener('change', () => renderClientsTable(allClients));
    
    // Create invoice button
    createInvoiceBtn.addEventListener('click', () => {
        resetInvoiceForm();
        openModal(invoiceModal);
        loadClientsForInvoice();
    });

    document.getElementById('addStaffBtn').addEventListener('click', () => {
        resetStaffForm();
        openModal(staffModal);
    });

    invoiceClientSelect.addEventListener('change', updateInvoiceClientDetails);
    document.getElementById('invoiceAmount').addEventListener('input', updateInvoiceTotals);
    document.getElementById('invoiceDiscountType').addEventListener('change', updateInvoiceTotals);
    document.getElementById('invoiceDiscountValue').addEventListener('input', updateInvoiceTotals);
    document.getElementById('invoiceReceivedAmount').addEventListener('input', updateInvoiceTotals);
    invoiceSearch.addEventListener('input', () => renderInvoicesTable(allInvoices));
    document.getElementById('saveInvoiceStatusBtn').addEventListener('click', saveInvoiceStatus);
    document.getElementById('cancelDeleteInvoiceBtn').addEventListener('click', cancelInvoiceDelete);
    document.getElementById('confirmDeleteInvoiceBtn').addEventListener('click', confirmInvoiceDelete);
    exportReportPdfBtn.addEventListener('click', () => downloadReport('pdf', exportReportPdfBtn));
    exportReportExcelBtn.addEventListener('click', () => downloadReport('excel', exportReportExcelBtn));
    referralFinancialYearSelect.addEventListener('change', loadReferralReport);
    referralClientSearch.addEventListener('input', loadReferralReport);
    exportReferralPdfBtn.addEventListener('click', () => downloadReferralReport('pdf', exportReferralPdfBtn));
    exportReferralExcelBtn.addEventListener('click', () => downloadReferralReport('excel', exportReferralExcelBtn));
    reportFinancialYearSelect.addEventListener('change', () => {
        loadReportSummary();
        loadReportRemarks();
    });
    document.getElementById('saveInvoiceDraftBtn').addEventListener('click', () => {
        document.getElementById('invoiceWorkflowStatus').value = 'draft';
        invoiceForm.requestSubmit();
    });
    document.getElementById('editReviewInvoiceBtn').addEventListener('click', () => {
        if (currentReviewInvoice) editInvoice(currentReviewInvoice.id);
    });
    document.getElementById('downloadReviewInvoiceBtn').addEventListener('click', () => {
        if (currentReviewInvoice) downloadInvoice(currentReviewInvoice.id);
    });
    document.getElementById('printReviewInvoiceBtn').addEventListener('click', () => {
        if (currentReviewInvoice) printInvoice(currentReviewInvoice.id);
    });
    document.getElementById('approveShareInvoiceBtn').addEventListener('click', approveAndShareInvoice);
    document.getElementById('markManualInvoiceSentBtn').addEventListener('click', markManualInvoiceSent);
    
    // Assign task button
    if (assignTaskBtn) {
        assignTaskBtn.addEventListener('click', () => {
            openModal(taskModal);
            loadStaffForTaskAssignment();
            loadClientsForTaskAssignment();
        });
    }
    
    // Close modal buttons
    closeModalBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            closeAllModals();
        });
    });
    
    // Form submissions
    clientForm.addEventListener('submit', handleClientSubmit);
    if (invoiceForm) invoiceForm.addEventListener('submit', handleInvoiceSubmit);
    if (taskForm) taskForm.addEventListener('submit', handleTaskSubmit);
    if (remarkForm) remarkForm.addEventListener('submit', handleRemarkSubmit);
    document.getElementById('cancelRemarkEditBtn').addEventListener('click', cancelClientRemarkEdit);
    if (staffForm) staffForm.addEventListener('submit', handleStaffSubmit);
    document.getElementById('createAdminNoteBtn').addEventListener('click', createAdminNote);
    document.getElementById('deleteAdminNoteBtn').addEventListener('click', deleteAdminNote);
    document.getElementById('adminNoteSearch').addEventListener('input', renderAdminNotesList);
    document.getElementById('adminNoteTitle').addEventListener('input', handleAdminNoteInput);
    document.getElementById('adminNoteContent').addEventListener('input', handleAdminNoteInput);
    window.addEventListener('beforeunload', event => {
        if (!adminNoteHasUnsavedChanges) return;
        event.preventDefault();
        event.returnValue = '';
    });

    ['remarkClientFilter', 'remarkStaffFilter', 'remarkCategoryFilter'].forEach(id => {
        const filter = document.getElementById(id);
        if (filter) {
            filter.addEventListener('input', renderRemarksTable);
            filter.addEventListener('change', renderRemarksTable);
        }
    });

    // Close modal when clicking outside
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            closeAllModals();
        }
    });
}

function closeMobileNavigation() {
    if (!dashboard.classList.contains('mobile-nav-open')) return;
    dashboard.classList.remove('mobile-nav-open');
    const toggle = document.getElementById('mobileNavToggle');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Open workspace navigation');
}

// Check login status
async function checkLoginStatus() {
    try {
        const response = await fetch('/api/dashboard');
        if (response.ok) {
            // User is logged in
            const data = await response.json();
            currentUser = {
                id: data.user_id,
                username: data.username,
                role: data.role
            };
            userRole.textContent = data.role.charAt(0).toUpperCase() + data.role.slice(1);
            userRole.className = `user-role ${data.role}`;
            userName.textContent = data.username;
            configureDashboardForRole();
            loginScreen.style.display = 'none';
            dashboard.style.display = 'block';
            loadDashboardData();
        } else {
            // User is not logged in
            loginScreen.style.display = 'flex';
            dashboard.style.display = 'none';
        }
    } catch (error) {
        console.error('Error checking login status:', error);
        loginScreen.style.display = 'flex';
        dashboard.style.display = 'none';
    }
}

function configureDashboardForRole() {
    const isAdmin = currentUser.role === 'admin';
    const staffTab = document.querySelector('.tab[data-tab="staff"]');
    const staffTabContent = document.getElementById('staffTab');
    const adminNotesTab = document.querySelector('.tab[data-tab="adminNotes"]');
    const adminNotesContent = document.getElementById('adminNotesTab');
    const adminProfileTab = document.getElementById('adminProfileNavTab');
    const adminProfileContent = document.getElementById('adminProfileTab');
    const sidebarAdminProfile = document.getElementById('sidebarAdminProfile');
    const headerAdminAvatar = document.getElementById('headerAdminAvatar');
    const taskAssignedToHeader = document.getElementById('taskAssignedToHeader');
    const clientAssignedToHeader = document.getElementById('clientAssignedToHeader');
    const clientStaffAssignment = document.getElementById('clientStaffAssignment');
    const taskStaffAssignment = document.getElementById('taskStaffAssignment');
    const taskAssignTo = document.getElementById('taskAssignTo');
    const remarkStaffFilter = document.getElementById('remarkStaffFilter');
    const remarkStaffHeader = document.getElementById('remarkStaffHeader');
    const remarkInvoicesHeader = document.getElementById('remarkInvoicesHeader');
    const remarkDateHeader = document.getElementById('remarkDateHeader');
    const remarkTimeHeader = document.getElementById('remarkTimeHeader');
    const remarkLastUpdatedHeader = document.getElementById('remarkLastUpdatedHeader');
    const remarkActionsHeader = document.getElementById('remarkActionsHeader');

    if (assignTaskBtn) assignTaskBtn.style.display = isAdmin ? '' : 'none';
    if (staffTab) staffTab.style.display = isAdmin ? '' : 'none';
    if (staffTabContent) staffTabContent.style.display = isAdmin ? '' : 'none';
    if (adminNotesTab) adminNotesTab.style.display = isAdmin ? '' : 'none';
    if (adminNotesContent) adminNotesContent.style.display = isAdmin ? '' : 'none';
    if (adminProfileTab) adminProfileTab.hidden = !isAdmin;
    if (adminProfileContent) adminProfileContent.style.display = isAdmin ? '' : 'none';
    if (sidebarAdminProfile) sidebarAdminProfile.hidden = !isAdmin;
    if (headerAdminAvatar) headerAdminAvatar.hidden = !isAdmin;
    if (taskAssignedToHeader) taskAssignedToHeader.style.display = isAdmin ? '' : 'none';
    if (clientAssignedToHeader) clientAssignedToHeader.style.display = isAdmin ? '' : 'none';
    if (clientStaffAssignment) clientStaffAssignment.style.display = isAdmin ? '' : 'none';
    if (taskStaffAssignment) taskStaffAssignment.style.display = isAdmin ? '' : 'none';
    if (taskAssignTo) taskAssignTo.required = isAdmin;
    if (createInvoiceBtn) createInvoiceBtn.style.display = isAdmin ? '' : 'none';
    const reportActions = document.querySelector('.report-actions');
    if (reportActions) reportActions.style.display = isAdmin ? '' : 'none';
    const referralReportSection = document.getElementById('referralReportSection');
    if (referralReportSection) referralReportSection.style.display = isAdmin ? '' : 'none';
    if (remarkStaffFilter) remarkStaffFilter.style.display = isAdmin ? '' : 'none';
    if (remarkStaffHeader) remarkStaffHeader.style.display = isAdmin ? 'table-cell' : 'none';
    if (remarkInvoicesHeader) remarkInvoicesHeader.style.display = isAdmin ? 'table-cell' : 'none';
    if (remarkDateHeader) remarkDateHeader.style.display = isAdmin ? 'table-cell' : 'none';
    if (remarkTimeHeader) remarkTimeHeader.style.display = isAdmin ? 'table-cell' : 'none';
    if (remarkLastUpdatedHeader) remarkLastUpdatedHeader.style.display = isAdmin ? 'none' : 'table-cell';
    if (remarkActionsHeader) remarkActionsHeader.style.display = isAdmin ? 'none' : 'table-cell';

    const addStaffBtn = document.getElementById('addStaffBtn');
    if (addStaffBtn) addStaffBtn.style.display = isAdmin ? '' : 'none';
}

// Handle login
async function handleLogin(e) {
    e.preventDefault();
    
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const userType = userTypeInput.value;
    const submitButton = loginForm.querySelector('button[type="submit"]');
    submitButton.disabled = true;
    
    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password, user_type: userType })
        });
        
        const data = await response.json();
        
        if (data.success) {
            window.location.assign('/');
        } else {
            alert('Login failed: ' + (data.message || 'Invalid credentials'));
        }
    } catch (error) {
        console.error('Login error:', error);
        alert('Login failed. Please try again.');
    } finally {
        submitButton.disabled = false;
    }
}

// Handle logout
function handleLogout() {
    window.location.href = '/logout';
}

// Load dashboard data
async function loadDashboardData() {
    try {
        configureDashboardForRole();

        if (currentUser.role === 'admin') {
            await loadAdminProfile();
        }
        
        // Load stats
        const statsResponse = await fetch('/api/dashboard');
        if (statsResponse.ok) {
            const stats = await statsResponse.json();
            updateStats(stats);
        }
        
        // Load clients
        const clientsResponse = await fetch('/api/clients');
        if (clientsResponse.ok) {
            const data = await clientsResponse.json();
            allClients = data.clients;
            await loadClientYearWiseData();
        }
        
        // Only administrators can view staff accounts.
        if (currentUser.role === 'admin') {
            const staffResponse = await fetch('/api/staff');
            if (staffResponse.ok) {
                const data = await staffResponse.json();
                allStaff = data.staff;
                renderStaffTable(allStaff);
            }
        }
        
        // Load invoices
        const invoicesResponse = await fetch('/api/invoices');
        if (invoicesResponse.ok) {
            const data = await invoicesResponse.json();
            allInvoices = data.invoices;
            renderInvoicesTable(allInvoices);
        }

        // Load tasks
        const tasksResponse = await fetch('/api/tasks');
        if (tasksResponse.ok) {
            const data = await tasksResponse.json();
            allTasks = data.tasks;
            renderTasksTable(allTasks);
            loadTaskStats();
        }
    } catch (error) {
        console.error('Error loading dashboard data:', error);
    }
}

async function loadClientYearWiseData() {
    try {
        const response = await fetch('/api/clients/year-wise');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load year-wise client totals.');

        clientYearWiseData = data;
        clientYearWiseError = '';
        const selectedYear = clientFinancialYearSelect.value;
        clientFinancialYearSelect.replaceChildren();

        const allYearsOption = document.createElement('option');
        allYearsOption.value = 'all';
        allYearsOption.textContent = `All Financial Years (${data.all_years.length})`;
        clientFinancialYearSelect.appendChild(allYearsOption);
        data.financial_years.forEach(year => {
            const option = document.createElement('option');
            option.value = year.value;
            option.textContent = `${year.label} (${year.client_count})`;
            clientFinancialYearSelect.appendChild(option);
        });
        clientFinancialYearSelect.value = data.financial_years.some(
            year => year.value === selectedYear
        ) ? selectedYear : 'all';
    } catch (error) {
        clientYearWiseError = error.message || 'Unable to load year-wise client totals.';
        console.error('Error loading year-wise client totals:', error);
    }
    renderClientsTable(allClients);
}

// Update statistics cards
function updateStats(stats) {
    statsContainer.innerHTML = `
        <div class="stat-card">
            <div class="stat-icon total">
                <i class="fas fa-users"></i>
            </div>
            <div class="stat-info">
                <h3>${stats.total}</h3>
                <p>Total Clients</p>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon pending">
                <i class="fas fa-clock"></i>
            </div>
            <div class="stat-info">
                <h3>${stats.pending}</h3>
                <p>Pending Cases</p>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon found">
                <i class="fas fa-check-circle"></i>
            </div>
            <div class="stat-info">
                <h3>${stats.found}</h3>
                <p>Documents Found</p>
            </div>
        </div>
        <div class="stat-card">
            <div class="stat-icon not-found">
                <i class="fas fa-times-circle"></i>
            </div>
            <div class="stat-info">
                <h3>${stats.not_found}</h3>
                <p>Not Found</p>
            </div>
        </div>
    `;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    statsContainer.querySelectorAll('.stat-info h3').forEach((counter, index) => {
        const target = Number(counter.textContent);
        if (!Number.isFinite(target) || reduceMotion) return;

        counter.textContent = '0';
        const startedAt = performance.now() + index * 75;
        const duration = 850;
        const animate = now => {
            const progress = Math.max(0, Math.min((now - startedAt) / duration, 1));
            counter.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
            if (progress < 1) requestAnimationFrame(animate);
        };
        requestAnimationFrame(animate);
    });
}

// Load task statistics
async function loadTaskStats() {
    try {
        const response = await fetch('/api/task-stats');
        if (response.ok) {
            const stats = await response.json();
            document.getElementById('pendingTasksCount').textContent = stats.pending;
            document.getElementById('inProgressTasksCount').textContent = stats.in_progress;
            document.getElementById('completedTasksCount').textContent = stats.completed;
        }
    } catch (error) {
        console.error('Error loading task stats:', error);
    }
}

// Switch between tabs
function switchTab(tabId) {
    tabs.forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabId);
    });
    
    tabContents.forEach(content => {
        content.classList.toggle('active', content.id === `${tabId}Tab`);
    });
    
    if (tabId === 'tasks') {
        loadTaskData();
    } else if (tabId === 'reports') {
        loadReports();
    } else if (tabId === 'remarks') {
        loadRemarksData();
    } else if (tabId === 'adminNotes') {
        loadAdminNotes();
    } else if (tabId === 'adminProfile' && currentUser?.role === 'admin') {
        loadAdminProfile();
    }
}

function showAdminProfileNotice(message, isError = false) {
    const notice = document.getElementById('adminProfileNotice');
    notice.textContent = message;
    notice.classList.toggle('is-error', isError);
    notice.classList.toggle('is-visible', Boolean(message));
}

function setAdminProfileAvatar(url) {
    const ids = [
        ['adminProfilePicture', 'adminProfilePictureFallback'],
        ['headerAdminAvatarImage', null],
        ['sidebarAdminAvatarImage', null]
    ];
    ids.forEach(([imageId, fallbackId]) => {
        const image = document.getElementById(imageId);
        if (!image) return;
        if (url) {
            image.src = url;
            image.hidden = false;
        } else {
            image.removeAttribute('src');
            image.hidden = true;
        }
        if (fallbackId) {
            document.getElementById(fallbackId).hidden = Boolean(url);
        } else {
            image.parentElement.classList.toggle('has-image', Boolean(url));
        }
    });
}

async function loadAdminProfile() {
    if (currentUser?.role !== 'admin') return;
    try {
        const response = await fetch('/api/admin/profile', { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load admin profile.');
        adminProfileCsrfToken = data.csrf_token;
        savedAdminProfile = {
            username: data.username,
            email: data.email || '',
            contact_number: data.contact_number || '',
            avatar_url: data.avatar_url
        };
        document.getElementById('adminProfileUsername').value = data.username;
        document.getElementById('adminProfileEmail').value = data.email || '';
        document.getElementById('adminProfileContact').value = data.contact_number || '';
        const avatarUrl = data.avatar_url ? `${data.avatar_url}?v=${Date.now()}` : '';
        setAdminProfileAvatar(avatarUrl);
    } catch (error) {
        showAdminProfileNotice(error.message || 'Unable to load admin profile.', true);
        console.error('Error loading admin profile:', error);
    }
}

function restoreAdminProfile() {
    if (!savedAdminProfile) return;
    document.getElementById('adminProfileEmail').value = savedAdminProfile.email;
    document.getElementById('adminProfileContact').value = savedAdminProfile.contact_number;
    showAdminProfileNotice('');
}

async function saveAdminProfile(event) {
    event.preventDefault();
    showAdminProfileNotice('');
    const payload = {
        email: document.getElementById('adminProfileEmail').value.trim(),
        contact_number: document.getElementById('adminProfileContact').value.trim()
    };
    try {
        const response = await fetch('/api/admin/profile', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-Admin-Profile-CSRF': adminProfileCsrfToken
            },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to save profile details.');
        showAdminProfileNotice(data.message || 'Profile details updated.');
        await loadAdminProfile();
    } catch (error) {
        showAdminProfileNotice(error.message || 'Unable to save profile details.', true);
    }
}

async function changeAdminPassword(event) {
    event.preventDefault();
    showAdminProfileNotice('');
    const form = event.currentTarget;
    const currentPassword = document.getElementById('adminCurrentPassword');
    const newPassword = document.getElementById('adminNewPassword');
    try {
        const response = await fetch('/api/admin/profile/password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Admin-Profile-CSRF': adminProfileCsrfToken
            },
            body: JSON.stringify({
                current_password: currentPassword.value,
                new_password: newPassword.value
            })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to change password.');
        form.reset();
        await loadAdminProfile();
        showAdminProfileNotice(data.message || 'Password changed successfully.');
    } catch (error) {
        currentPassword.value = '';
        newPassword.value = '';
        showAdminProfileNotice(error.message || 'Unable to change password.', true);
    }
}

async function uploadAdminPicture(event) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) return;
    showAdminProfileNotice('');
    const formData = new FormData();
    formData.append('profile_picture', file);
    try {
        const response = await fetch('/api/admin/profile/avatar', {
            method: 'POST',
            headers: { 'X-Admin-Profile-CSRF': adminProfileCsrfToken },
            body: formData
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to upload profile picture.');
        setAdminProfileAvatar(`${data.avatar_url}&t=${Date.now()}`);
        savedAdminProfile = { ...savedAdminProfile, avatar_url: data.avatar_url };
        showAdminProfileNotice(data.message || 'Profile picture updated.');
    } catch (error) {
        showAdminProfileNotice(error.message || 'Unable to upload profile picture.', true);
    } finally {
        input.value = '';
    }
}

async function removeAdminPicture() {
    showAdminProfileNotice('');
    try {
        const response = await fetch('/api/admin/profile/avatar', {
            method: 'DELETE',
            headers: { 'X-Admin-Profile-CSRF': adminProfileCsrfToken }
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to remove profile picture.');
        setAdminProfileAvatar('');
        if (savedAdminProfile) savedAdminProfile.avatar_url = null;
        showAdminProfileNotice(data.message || 'Profile picture removed.');
    } catch (error) {
        showAdminProfileNotice(error.message || 'Unable to remove profile picture.', true);
    }
}

async function loadAdminNotes() {
    if (!currentUser || currentUser.role !== 'admin') return;
    const status = document.getElementById('adminNoteSaveStatus');
    if (adminNotesLoaded) {
        renderAdminNotesList();
        const selectedNoteExists = adminNotes.some(note => note.id === selectedAdminNoteId);
        if (!selectedNoteExists && adminNotes.length) showAdminNote(adminNotes[0]);
        else if (!selectedNoteExists) {
            clearAdminNoteEditor();
            status.textContent = 'No notes yet. Create a note to get started.';
        }
        return;
    }
    status.textContent = 'Loading notes...';
    try {
        const response = await fetch('/api/admin/notes');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load your notes.');
        adminNotes = data.notes;
        adminNotesLoaded = true;
        selectedAdminNoteId = null;
        renderAdminNotesList();
        const firstNote = adminNotes[0];
        if (firstNote) {
            showAdminNote(firstNote);
        } else {
            clearAdminNoteEditor();
            status.textContent = 'No notes yet. Create a note to get started.';
        }
    } catch (error) {
        console.error('Error loading Admin notes:', error);
        status.textContent = error.message || 'Unable to load your notes.';
    }
}

function renderAdminNotesList() {
    const list = document.getElementById('adminNotesList');
    const status = document.getElementById('adminNotesListStatus');
    if (!list) return;
    const searchTerm = document.getElementById('adminNoteSearch').value.trim().toLowerCase();
    const visibleNotes = adminNotes.filter(note =>
        note.title.toLowerCase().includes(searchTerm) ||
        note.content.toLowerCase().includes(searchTerm)
    );
    list.replaceChildren();
    status.textContent = visibleNotes.length === 1
        ? '1 note'
        : `${visibleNotes.length} notes`;
    if (!visibleNotes.length) {
        const empty = document.createElement('p');
        empty.className = 'admin-notes-empty';
        empty.textContent = adminNotes.length
            ? 'No notes match your search.'
            : 'Your saved notes will appear here.';
        list.appendChild(empty);
        return;
    }

    visibleNotes.forEach(note => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'admin-note-list-item';
        button.classList.toggle('active', note.id === selectedAdminNoteId);
        button.setAttribute('role', 'listitem');
        const title = document.createElement('strong');
        title.textContent = note.title;
        const updated = document.createElement('span');
        updated.textContent = `Updated ${formatAdminNoteDate(note.updated_at)}`;
        button.append(title, updated);
        button.addEventListener('click', () => selectAdminNote(note.id));
        list.appendChild(button);
    });
}

function formatAdminNoteDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'recently';
    return date.toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short'
    });
}

function showAdminNote(note) {
    selectedAdminNoteId = note.id;
    document.getElementById('adminNoteTitle').value = note.title;
    document.getElementById('adminNoteContent').value = note.content;
    document.getElementById('adminNoteTitle').disabled = false;
    document.getElementById('adminNoteContent').disabled = false;
    document.getElementById('deleteAdminNoteBtn').disabled = false;
    document.getElementById('adminNoteSaveStatus').textContent =
        `Saved ${formatAdminNoteDate(note.updated_at)}`;
    adminNoteHasUnsavedChanges = false;
    renderAdminNotesList();
}

function clearAdminNoteEditor() {
    selectedAdminNoteId = null;
    document.getElementById('adminNoteTitle').value = '';
    document.getElementById('adminNoteContent').value = '';
    document.getElementById('adminNoteTitle').disabled = true;
    document.getElementById('adminNoteContent').disabled = true;
    document.getElementById('deleteAdminNoteBtn').disabled = true;
    adminNoteHasUnsavedChanges = false;
    renderAdminNotesList();
}

async function flushAdminNoteSave() {
    if (adminNoteSaveTimer) {
        window.clearTimeout(adminNoteSaveTimer);
        adminNoteSaveTimer = null;
        queueAdminNoteSave();
    } else if (adminNoteHasUnsavedChanges) {
        queueAdminNoteSave();
    }
    await adminNoteSavePromise;
    return !adminNoteHasUnsavedChanges;
}

async function selectAdminNote(noteId) {
    if (noteId === selectedAdminNoteId) return;
    if (!(await flushAdminNoteSave())) return;
    const note = adminNotes.find(item => item.id === noteId);
    if (note) showAdminNote(note);
}

async function createAdminNote() {
    if (!currentUser || currentUser.role !== 'admin') return;
    if (!(await flushAdminNoteSave())) return;
    const status = document.getElementById('adminNoteSaveStatus');
    status.textContent = 'Creating note...';
    try {
        const response = await fetch('/api/admin/notes', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to create a note.');
        adminNotes.unshift(data.note);
        showAdminNote(data.note);
        renderAdminNotesList();
        document.getElementById('adminNoteTitle').focus();
    } catch (error) {
        console.error('Error creating Admin note:', error);
        status.textContent = error.message || 'Unable to create a note.';
    }
}

function handleAdminNoteInput() {
    if (!selectedAdminNoteId) return;
    adminNoteEditVersion += 1;
    adminNoteHasUnsavedChanges = true;
    const note = adminNotes.find(item => item.id === selectedAdminNoteId);
    if (note) {
        note.title = document.getElementById('adminNoteTitle').value.trim() || 'Untitled note';
        note.content = document.getElementById('adminNoteContent').value;
    }
    document.getElementById('adminNoteSaveStatus').textContent = 'Unsaved changes';
    if (adminNoteSaveTimer) window.clearTimeout(adminNoteSaveTimer);
    adminNoteSaveTimer = window.setTimeout(() => {
        adminNoteSaveTimer = null;
        queueAdminNoteSave();
    }, 600);
    renderAdminNotesList();
}

function queueAdminNoteSave() {
    const noteId = selectedAdminNoteId;
    if (!noteId) return;
    const version = adminNoteEditVersion;
    const title = document.getElementById('adminNoteTitle').value.trim() || 'Untitled note';
    const content = document.getElementById('adminNoteContent').value;
    document.getElementById('adminNoteSaveStatus').textContent = 'Saving...';
    adminNoteSavePromise = adminNoteSavePromise.catch(() => {}).then(async () => {
        const response = await fetch(`/api/admin/notes/${noteId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, content })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to save this note.');
        const noteIndex = adminNotes.findIndex(note => note.id === noteId);
        if (noteIndex !== -1) {
            const currentNote = adminNotes[noteIndex];
            adminNotes[noteIndex] = {
                ...data.note,
                title: version === adminNoteEditVersion ? data.note.title : currentNote.title,
                content: version === adminNoteEditVersion ? data.note.content : currentNote.content
            };
            adminNotes.sort((first, second) =>
                new Date(second.updated_at) - new Date(first.updated_at)
            );
        }
        if (selectedAdminNoteId === noteId && adminNoteEditVersion === version) {
            adminNoteHasUnsavedChanges = false;
            document.getElementById('adminNoteSaveStatus').textContent =
                `Saved ${formatAdminNoteDate(data.note.updated_at)}`;
        }
        renderAdminNotesList();
        if (selectedAdminNoteId === noteId && adminNoteEditVersion !== version &&
            !adminNoteSaveTimer) {
            queueAdminNoteSave();
        }
    }).catch(error => {
        console.error('Error saving Admin note:', error);
        if (selectedAdminNoteId === noteId) {
            adminNoteHasUnsavedChanges = true;
            document.getElementById('adminNoteSaveStatus').textContent =
                error.message || 'Save failed. Your changes are still here; retry by editing.';
        }
    });
}

async function deleteAdminNote() {
    if (!selectedAdminNoteId) return;
    if (!window.confirm('Delete this note? This action cannot be undone.')) return;
    if (!(await flushAdminNoteSave())) return;
    const noteId = selectedAdminNoteId;
    const status = document.getElementById('adminNoteSaveStatus');
    status.textContent = 'Deleting note...';
    try {
        const response = await fetch(`/api/admin/notes/${noteId}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to delete this note.');
        adminNotes = adminNotes.filter(note => note.id !== noteId);
        clearAdminNoteEditor();
        if (adminNotes.length) showAdminNote(adminNotes[0]);
        else status.textContent = 'Note deleted. Create another note whenever you need one.';
    } catch (error) {
        console.error('Error deleting Admin note:', error);
        status.textContent = error.message || 'Unable to delete this note.';
    }
}

async function loadRemarksData() {
    const remarksTableBody = document.getElementById('remarksTableBody');
    const loadingRow = document.createElement('tr');
    const loadingCell = document.createElement('td');
    loadingCell.colSpan = currentUser && currentUser.role === 'admin' ? 8 : 6;
    loadingCell.className = 'remarks-empty';
    loadingCell.textContent = 'Loading remarks...';
    loadingRow.appendChild(loadingCell);
    remarksTableBody.replaceChildren(loadingRow);

    try {
        const response = await fetch('/api/remarks');
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Unable to load remarks.');
        }
        allRemarks = data.remarks;
        renderRemarksTable();
    } catch (error) {
        console.error('Error loading remarks:', error);
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = currentUser && currentUser.role === 'admin' ? 8 : 6;
        cell.className = 'remarks-empty';
        cell.textContent = error.message || 'Unable to load remarks.';
        row.appendChild(cell);
        remarksTableBody.replaceChildren(row);
    }
}

function addRemarkText(cell, text, useDetails = false) {
    if (useDetails && text.length > 140) {
        const details = document.createElement('details');
        details.className = 'remark-details';
        const summary = document.createElement('summary');
        summary.textContent = 'View remark';
        const content = document.createElement('p');
        content.textContent = text;
        details.append(summary, content);
        cell.appendChild(details);
        return;
    }
    cell.textContent = text;
}

function renderRemarksTable() {
    const remarksTableBody = document.getElementById('remarksTableBody');
    if (!remarksTableBody || !currentUser) return;

    const isAdmin = currentUser.role === 'admin';
    const clientFilter = document.getElementById('remarkClientFilter').value.trim().toLowerCase();
    const staffFilter = isAdmin
        ? document.getElementById('remarkStaffFilter').value.trim().toLowerCase()
        : '';
    const categoryFilter = document.getElementById('remarkCategoryFilter').value;
    const filteredRemarks = allRemarks.filter(remark =>
        remark.client_name.toLowerCase().includes(clientFilter) &&
        (!staffFilter || (remark.staff_name || '').toLowerCase().includes(staffFilter)) &&
        (!categoryFilter || remark.category === categoryFilter)
    );

    remarksTableBody.innerHTML = '';
    if (filteredRemarks.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = isAdmin ? 8 : 6;
        cell.className = 'remarks-empty';
        cell.textContent = allRemarks.length ? 'No remarks match these filters.' : 'No remarks have been saved yet.';
        row.appendChild(cell);
        remarksTableBody.appendChild(row);
        return;
    }

    filteredRemarks.forEach(remark => {
        const row = document.createElement('tr');
        const addCell = (value, className = '') => {
            const cell = document.createElement('td');
            cell.textContent = value || '';
            if (className) cell.className = className;
            row.appendChild(cell);
            return cell;
        };
        addCell(remark.client_name);
        addCell(remark.pan_number || '');
        if (isAdmin) {
            addCell(remark.staff_name || '');
            addCell((remark.invoice_numbers || []).join(', ') || '-');
        }
        addCell(remark.category);
        const remarkCell = addCell('', 'remark-description');
        addRemarkText(remarkCell, remark.remark, isAdmin);
        if (isAdmin) {
            addCell(remark.remark_date || '');
            addCell(remark.remark_time || '');
        } else {
            addCell(remark.updated_at || '');
        }

        if (!isAdmin) {
            const actions = document.createElement('td');
            actions.className = 'remark-row-actions';
            const editButton = document.createElement('button');
            editButton.type = 'button';
            editButton.className = 'action-btn edit';
            editButton.innerHTML = '<i class="fas fa-edit"></i> Edit';
            editButton.addEventListener('click', () => openClientRemark(remark.client_id));
            actions.appendChild(editButton);
            row.appendChild(actions);
        }
        remarksTableBody.appendChild(row);
    });
}

// Load task data
async function loadTaskData() {
    try {
        const response = await fetch('/api/tasks');
        if (response.ok) {
            const data = await response.json();
            allTasks = data.tasks;
            renderTasksTable(allTasks);
            loadTaskStats();
        }
    } catch (error) {
        console.error('Error loading tasks:', error);
    }
}

// Render tasks table
function renderTasksTable(tasks) {
    const tasksTableBody = document.getElementById('tasksTableBody');
    if (!tasksTableBody) return;
    const isAdmin = currentUser.role === 'admin';
    
    tasksTableBody.innerHTML = '';
    
    if (tasks.length === 0) {
        tasksTableBody.innerHTML = `<tr><td colspan="${isAdmin ? 7 : 6}" style="text-align: center; padding: 20px; color: #999;">No tasks assigned yet</td></tr>`;
        return;
    }
    
    tasks.forEach(task => {
        const row = document.createElement('tr');
        
        let priorityClass = 'priority-low';
        let priorityIcon = 'fa-arrow-down';
        if (task.priority === 'medium') {
            priorityClass = 'priority-medium';
            priorityIcon = 'fa-minus';
        } else if (task.priority === 'high') {
            priorityClass = 'priority-high';
            priorityIcon = 'fa-arrow-up';
        } else if (task.priority === 'critical') {
            priorityClass = 'priority-critical';
            priorityIcon = 'fa-exclamation-circle';
        }
        
        let statusClass = 'status-pending';
        let statusText = 'Pending';
        if (task.status === 'in_progress') {
            statusClass = 'status-in-progress';
            statusText = 'In Progress';
        } else if (task.status === 'completed') {
            statusClass = 'status-found';
            statusText = 'Completed';
        } else if (task.status === 'on_hold') {
            statusClass = 'status-on-hold';
            statusText = 'On Hold';
        }
        
        row.innerHTML = `
            <td><strong>${task.title}</strong></td>
            <td>${task.client_name}</td>
            ${isAdmin ? `<td>${task.assigned_to}</td>` : ''}
            <td><span class="priority-badge ${priorityClass}"><i class="fas ${priorityIcon}"></i> ${task.priority.charAt(0).toUpperCase() + task.priority.slice(1)}</span></td>
            <td><span class="status-badge ${statusClass}">${statusText}</span></td>
            <td>${task.due_date}</td>
            <td>
                <div class="action-btns">
                    <button class="action-btn edit" onclick="editTask(${task.id})">
                        <i class="fas fa-edit"></i> Edit
                    </button>
                    <button class="action-btn delete" onclick="deleteTask(${task.id})">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </div>
            </td>
        `;
        
        tasksTableBody.appendChild(row);
    });
}

// Render clients table
function renderClientsTable(clients) {
    if (!clientsTableBody || !currentUser) return;
    clientsTableBody.innerHTML = '';
    const isAdmin = currentUser.role === 'admin';

    const selectedYear = clientFinancialYearSelect?.value || 'all';
    const yearRecords = clientYearWiseData
        ? (selectedYear === 'all'
            ? clientYearWiseData.all_years
            : clientYearWiseData.clients_by_year[selectedYear] || [])
        : clients.map(client => ({
            ...client,
            total_invoices: 0,
            total_invoice_amount: 0,
            financial_year: 'All Financial Years'
        }));
    const search = (document.getElementById('searchClient')?.value || '').trim().toLowerCase();
    const filteredClients = yearRecords.filter(client =>
        [client.client_name, client.email, client.pan_number, client.phone]
            .some(value => (value || '').toLowerCase().includes(search))
    );
    const selectedYearLabel = selectedYear === 'all'
        ? 'All Financial Years'
        : `FY ${selectedYear}`;

    if (clientYearCount) {
        const noun = filteredClients.length === 1 ? 'client' : 'clients';
        clientYearCount.textContent = clientYearWiseError
            ? `Invoice totals unavailable: ${clientYearWiseError}`
            : `Showing ${filteredClients.length} of ${yearRecords.length} ${noun} for ${selectedYearLabel}.`;
    }

    if (filteredClients.length === 0) {
        const message = yearRecords.length
            ? 'No clients match your search.'
            : (selectedYear === 'all' ? 'No clients yet.' : `No clients with invoices in FY ${selectedYear}.`);
        clientsTableBody.innerHTML = `<tr><td colspan="${isAdmin ? 10 : 9}" style="text-align: center; padding: 20px; color: #999;">${message}</td></tr>`;
        return;
    }

    filteredClients.forEach(client => {
        const row = document.createElement('tr');

        const values = [
            client.client_name,
            client.email || '—',
            client.pan_number || '—',
            client.phone,
            String(client.total_invoices),
            `₹${Number(client.total_invoice_amount).toFixed(2)}`,
            client.financial_year
        ];
        values.forEach(value => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });

        const statusCell = document.createElement('td');
        const statusBadge = document.createElement('span');
        const statusValues = {
            found: ['status-found', 'Found'],
            not_found: ['status-not-found', 'Not Found'],
            pending: ['status-pending', 'Pending']
        };
        const [statusClass, statusText] = statusValues[client.status] || statusValues.pending;
        statusBadge.className = `status-badge ${statusClass}`;
        statusBadge.textContent = statusText;
        statusCell.appendChild(statusBadge);
        row.appendChild(statusCell);

        if (isAdmin) {
            const assignedCell = document.createElement('td');
            assignedCell.textContent = client.assigned_to || 'Unassigned';
            row.appendChild(assignedCell);
        }

        const actionsCell = document.createElement('td');
        actionsCell.className = 'client-actions-cell';
        const actions = document.createElement('div');
        actions.className = 'action-btns client-action-grid';
        const addAction = (label, className, iconClass, handler) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `action-btn ${className}`;
            const icon = document.createElement('i');
            icon.className = iconClass;
            button.append(icon, document.createTextNode(` ${label}`));
            button.addEventListener('click', handler);
            actions.appendChild(button);
        };
        addAction('View', 'edit', 'fas fa-eye', () => viewClientDetails(client));
        addAction('Edit', 'edit', 'fas fa-edit', () => editClient(client.id));
        if (isAdmin) {
            addAction('Delete', 'delete', 'fas fa-trash', () => deleteClient(client.id));
        }
        const canManageRemarks = currentUser.role === 'admin' ||
            (currentUser.role === 'staff' && client.can_manage_remarks === true);
        if (canManageRemarks) {
            addAction('Notepad', 'remark', 'fas fa-note-sticky', () => openClientRemark(client.id));
        }
        addAction('WhatsApp', 'whatsapp', 'fab fa-whatsapp', () => messageOnWhatsApp(client.phone));
        addAction('Invoice', 'invoice', 'fas fa-file-invoice', () => createInvoiceForClient(client.id));
        actionsCell.appendChild(actions);
        row.appendChild(actionsCell);
        clientsTableBody.appendChild(row);
    });
}

function viewClientDetails(client) {
    const details = [
        ['Client name', client.client_name],
        ['Contact number', client.phone],
        ['Email', client.email],
        ['PAN number', client.pan_number],
        ['Status', client.status],
        ['Referred by', client.referred_by_name]
    ];
    const content = document.getElementById('clientDetailsContent');
    content.replaceChildren();
    details.forEach(([label, value]) => {
        const item = document.createElement('div');
        item.className = 'client-details-item';
        const heading = document.createElement('strong');
        heading.textContent = label;
        const detail = document.createElement('span');
        detail.textContent = value || '—';
        item.append(heading, detail);
        content.appendChild(item);
    });
    document.getElementById('clientDetailsTitle').textContent =
        `Client Details · ${client.client_name}`;
    openModal(document.getElementById('clientDetailsModal'));
}

// Render staff table
function renderStaffTable(staff) {
    const staffTableBody = document.getElementById('staffTableBody');
    if (!staffTableBody) return;
    
    staffTableBody.innerHTML = '';
    
    if (staff.length === 0) {
        staffTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 20px; color: #999;">No staff members yet</td></tr>';
        return;
    }
    
    staff.forEach(staffMember => {
        const row = document.createElement('tr');
        const assignedCount = allClients.filter(client => client.assigned_to === staffMember.username).length;
        const nameCell = document.createElement('td');
        nameCell.textContent = staffMember.full_name || staffMember.username;
        const emailCell = document.createElement('td');
        emailCell.textContent = staffMember.email || staffMember.username;
        const contactCell = document.createElement('td');
        contactCell.textContent = staffMember.contact_number || '—';
        const statusCell = document.createElement('td');
        const statusBadge = document.createElement('span');
        statusBadge.className = `status-badge ${staffMember.is_active ? 'status-found' : 'status-not-found'}`;
        statusBadge.textContent = staffMember.is_active ? 'Active' : 'Inactive';
        statusCell.appendChild(statusBadge);
        const assignedCell = document.createElement('td');
        assignedCell.textContent = `${assignedCount} clients`;
        const actionsCell = document.createElement('td');
        const actions = document.createElement('div');
        actions.className = 'action-btns';

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'action-btn edit';
        editButton.innerHTML = '<i class="fas fa-edit"></i> Edit / Reset Password';
        editButton.addEventListener('click', () => editStaff(staffMember.id));
        actions.appendChild(editButton);

        const statusButton = document.createElement('button');
        statusButton.type = 'button';
        statusButton.className = 'action-btn';
        statusButton.textContent = staffMember.is_active ? 'Deactivate' : 'Activate';
        statusButton.addEventListener('click', () => setStaffActive(staffMember.id, !staffMember.is_active));
        actions.appendChild(statusButton);

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'action-btn delete';
        deleteButton.innerHTML = '<i class="fas fa-trash"></i> Delete';
        deleteButton.addEventListener('click', () => deleteStaff(staffMember.id));
        actions.appendChild(deleteButton);
        actionsCell.appendChild(actions);

        [nameCell, emailCell, contactCell, statusCell, assignedCell, actionsCell].forEach(cell => row.appendChild(cell));
        staffTableBody.appendChild(row);
    });
}

// Render invoices table
function renderInvoicesTable(invoices) {
    const invoicesTableBody = document.getElementById('invoicesTableBody');
    if (!invoicesTableBody) return;
    
    invoicesTableBody.innerHTML = '';
    const search = (invoiceSearch?.value || '').trim().toLowerCase();
    const filteredInvoices = invoices.filter(invoice =>
        (invoice.client_name || '').toLowerCase().includes(search) ||
        (invoice.invoice_number || '').toLowerCase().includes(search)
    );
    
    if (filteredInvoices.length === 0) {
        invoicesTableBody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 20px; color: #777;">${invoices.length ? 'No matching invoices.' : 'No invoices yet'}</td></tr>`;
        return;
    }
    
    filteredInvoices.forEach(invoice => {
        const row = document.createElement('tr');
        const values = [
            invoice.invoice_number,
            invoice.client_name,
            `₹${parseFloat(invoice.amount).toFixed(2)}`,
            `${invoice.discount_type === 'fixed'
                ? `Fixed ₹${Number(invoice.discount_value || 0).toFixed(2)}`
                : `${Number(invoice.discount_value || 0)}%`} · -₹${Number(invoice.discount_amount || 0).toFixed(2)}`,
            `₹${parseFloat(invoice.total || invoice.amount).toFixed(2)}`,
            invoice.date
        ];
        values.forEach(value => {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        });
        const statusCell = document.createElement('td');
        const statusBadge = document.createElement('span');
        statusBadge.className = `status-badge ${invoice.status === 'paid' ? 'status-found' : 'status-pending'}`;
        statusBadge.textContent = invoice.status;
        statusCell.appendChild(statusBadge);
        row.appendChild(statusCell);

        const approvalCell = document.createElement('td');
        const approvalBadge = document.createElement('span');
        approvalBadge.className = 'invoice-state-badge';
        approvalBadge.textContent = (invoice.workflow_status || 'approved').replaceAll('_', ' ');
        approvalCell.appendChild(approvalBadge);
        row.appendChild(approvalCell);

        const deliveryCell = document.createElement('td');
        const deliveryBadge = document.createElement('span');
        deliveryBadge.className = `invoice-state-badge delivery-${invoice.delivery_status || 'legacy_unknown'}`;
        deliveryBadge.textContent = (invoice.delivery_status || 'legacy_unknown').replaceAll('_', ' ');
        deliveryCell.appendChild(deliveryBadge);
        row.appendChild(deliveryCell);

        const actionsCell = document.createElement('td');
        const actions = document.createElement('div');
        actions.className = 'action-btns';
        const addButton = (label, className, handler) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `action-btn ${className}`;
            button.textContent = label;
            button.addEventListener('click', handler);
            actions.appendChild(button);
        };
        addButton('Review', 'edit', () => reviewInvoice(invoice.id));
        addButton('Print', 'invoice', () => printInvoice(invoice.id));
        addButton('PDF', 'invoice', () => downloadInvoice(invoice.id));
        if (currentUser.role === 'admin') {
            if (['draft', 'pending_review'].includes(invoice.workflow_status)) {
                addButton('Edit', 'edit', () => editInvoice(invoice.id));
            } else if (invoice.workflow_status === 'approved' &&
                !['sending', 'sent', 'legacy_unknown'].includes(invoice.delivery_status)) {
                addButton('WhatsApp', 'whatsapp', () => approveAndShareInvoice(invoice.id));
            }
            addButton('Update Status', 'edit', () => viewInvoice(invoice.id, true));
            addButton('Delete', 'delete', () => deleteInvoice(invoice.id));
        }
        actionsCell.appendChild(actions);
        row.appendChild(actionsCell);
        invoicesTableBody.appendChild(row);
    });
}

// Handle client form submission
async function handleClientSubmit(e) {
    e.preventDefault();
    const errorElement = document.getElementById('clientFormError');
    const submitButton = document.getElementById('saveClientBtn');
    errorElement.textContent = '';

    const formData = new FormData(clientForm);
    const clientId = clientForm.dataset.clientId;
    const clientData = {
        client_name: String(formData.get('client_name') || '').trim(),
        email: String(formData.get('email') || '').trim().toLowerCase() || null,
        pan_number: String(formData.get('pan_number') || '').trim().toUpperCase() || null,
        phone: String(formData.get('phone') || '').replace(/\D/g, ''),
        status: formData.get('status'),
        referred_by_id: formData.get('referred_by_id') === 'none'
            ? null
            : (formData.get('referred_by_id') || null)
    };
    const password = String(formData.get('password') || '');
    if (!clientId || password) clientData.password = password;
    if (currentUser.role === 'admin') {
        clientData.assigned_to = formData.get('assigned_to') || null;
    }

    submitButton.disabled = true;
    let responseStatus = null;
    try {
        const response = await fetch(clientId ? `/api/clients/${clientId}` : '/api/clients', {
            method: clientId ? 'PUT' : 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(clientData)
        });

        responseStatus = response.status;
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || data.message ||
                `Unable to ${clientId ? 'update' : 'add'} client (HTTP ${response.status}).`);
        }

        closeAllModals();
        resetClientForm();
        if (data.client && !clientId) {
            allClients.push(data.client);
            renderClientsTable(allClients);
        }
        alert(data.message || (clientId ? 'Client updated successfully!' : 'Client added successfully!'));
        await loadDashboardData();
    } catch (error) {
        if (responseStatus === null || responseStatus >= 500) {
            console.error(`Error ${clientId ? 'updating' : 'adding'} client:`, error);
        }
        errorElement.textContent = error.message || 'Unable to save client. Please try again.';
    } finally {
        submitButton.disabled = false;
    }
}

function resetClientForm() {
    clientForm.reset();
    delete clientForm.dataset.clientId;
    referrerSearch.value = '';
    populateReferrerOptions();
    document.getElementById('clientFormError').textContent = '';
    document.querySelector('#addClientModal .modal-header h3').textContent = 'Add New Client';
    document.getElementById('saveClientBtn').textContent = 'Save Client';
}

function populateReferrerOptions(selectedId = '', selectedName = '') {
    const clientId = Number(clientForm.dataset.clientId || 0);
    const searchTerm = referrerSearch.value.trim().toLowerCase();
    const eligibleClients = allClients.filter(client => client.id !== clientId);
    const matchingClients = eligibleClients.filter(client =>
        client.client_name.toLowerCase().includes(searchTerm)
    );
    const selectedClient = eligibleClients.find(client => String(client.id) === String(selectedId));
    if (selectedClient && !matchingClients.some(client => client.id === selectedClient.id)) {
        matchingClients.unshift(selectedClient);
    }

    referrerClientSelect.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a referrer or leave blank';
    referrerClientSelect.appendChild(placeholder);

    const directOption = document.createElement('option');
    directOption.value = 'none';
    directOption.textContent = 'Direct / No Referral';
    referrerClientSelect.appendChild(directOption);

    matchingClients.forEach(client => {
        const option = document.createElement('option');
        option.value = String(client.id);
        option.textContent = `${client.client_name} (#${client.id})`;
        referrerClientSelect.appendChild(option);
    });

    if (selectedId && !selectedClient && selectedName) {
        const option = document.createElement('option');
        option.value = String(selectedId);
        option.textContent = `${selectedName} (#${selectedId})`;
        referrerClientSelect.appendChild(option);
    }
    referrerClientSelect.value = selectedId ? String(selectedId) : '';
}

// Handle task form submission
async function handleTaskSubmit(e) {
    e.preventDefault();
    
    const formData = new FormData(taskForm);
    const taskData = {
        title: formData.get('title'),
        description: formData.get('description'),
        assigned_to: parseInt(formData.get('assigned_to')),
        client_id: formData.get('client_id') || null,
        priority: formData.get('priority'),
        status: formData.get('status'),
        due_date: formData.get('due_date') || null
    };
    
    try {
        const response = await fetch('/api/tasks', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(taskData)
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Task assigned successfully!');
            closeAllModals();
            taskForm.reset();
            loadTaskData();
        } else {
            alert('Error assigning task: ' + (data.message || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error assigning task:', error);
        alert('Error assigning task. Please try again.');
    }
}

// Handle invoice form submission
async function handleInvoiceSubmit(e) {
    e.preventDefault();
    if (currentUser.role !== 'admin') return;
    if (!invoiceForm.reportValidity()) return;

    const submitButton = document.getElementById('generateInvoiceBtn');
    const clientId = Number(invoiceClientSelect.value);
    const editId = document.getElementById('invoiceEditId').value;
    const invoiceData = {
        client_id: clientId,
        amount: document.getElementById('invoiceAmount').value,
        discount_type: document.getElementById('invoiceDiscountType').value,
        discount_value: document.getElementById('invoiceDiscountValue').value || '0',
        received_amount: document.getElementById('invoiceReceivedAmount').value || '0',
        service_description: document.getElementById('invoiceServiceDescription').value.trim(),
        status: document.getElementById('invoiceStatus').value,
        workflow_status: document.getElementById('invoiceWorkflowStatus').value,
        request_token: document.getElementById('invoiceRequestToken').value
    };

    if ((!clientId && !editId) || !invoiceData.request_token) {
        alert('Select a client before generating the invoice.');
        return;
    }
    submitButton.disabled = true;

    try {
        const response = await fetch(editId ? `/api/invoices/${editId}` : '/api/invoices', {
            method: editId ? 'PUT' : 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(invoiceData)
        });
        
        const data = await response.json();
        
        if (!response.ok || (!editId && !data.success)) {
            throw new Error(data.error || data.message || 'Unable to generate invoice.');
        }

        const invoicesResponse = await fetch('/api/invoices');
        const invoicesData = await invoicesResponse.json();
        if (!invoicesResponse.ok) throw new Error(invoicesData.error || 'Invoice saved, but the list could not be refreshed.');
        allInvoices = invoicesData.invoices;
        renderInvoicesTable(allInvoices);
        await loadClientYearWiseData();
        const savedInvoiceId = editId ? data.id : (data.invoice_id || data.id);
        closeAllModals();
        resetInvoiceForm();
        if (!savedInvoiceId) throw new Error('Invoice saved, but its review record could not be loaded.');
        if (invoiceData.workflow_status === 'draft') {
            alert(`Invoice ${data.invoice_number} saved as a draft.`);
            return;
        }
        await reviewInvoice(savedInvoiceId);
    } catch (error) {
        console.error('Error creating invoice:', error);
        alert(error.message);
    } finally {
        submitButton.disabled = false;
    }
}

// Load staff for assignment dropdown
async function loadStaffForAssignment() {
    if (currentUser.role !== 'admin') return;

    try {
        const response = await fetch('/api/staff');
        if (response.ok) {
            const data = await response.json();
            assignStaffSelect.innerHTML = '<option value="">Unassigned</option>';
            data.staff.filter(staff => staff.is_active).forEach(staff => {
                const option = document.createElement('option');
                option.value = staff.id;
                option.textContent = staff.full_name || staff.username;
                assignStaffSelect.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading staff:', error);
    }
}

// Load staff for task assignment
async function loadStaffForTaskAssignment() {
    if (currentUser.role !== 'admin') return;

    try {
        const response = await fetch('/api/staff');
        if (response.ok) {
            const data = await response.json();
            const taskAssignTo = document.getElementById('taskAssignTo');
            taskAssignTo.innerHTML = '<option value="">Select Staff</option>';
            data.staff.filter(staff => staff.is_active).forEach(staff => {
                const option = document.createElement('option');
                option.value = staff.id;
                option.textContent = staff.full_name || staff.username;
                taskAssignTo.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading staff:', error);
    }
}

// Load clients for task assignment
async function loadClientsForTaskAssignment() {
    try {
        const response = await fetch('/api/clients');
        if (response.ok) {
            const data = await response.json();
            const taskClient = document.getElementById('taskClient');
            taskClient.innerHTML = '<option value="">General Task</option>';
            data.clients.forEach(client => {
                const option = document.createElement('option');
                option.value = client.id;
                option.textContent = `${client.client_name}${client.pan_number ? ` (${client.pan_number})` : ''}`;
                taskClient.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading clients:', error);
    }
}

// Load clients for invoice dropdown
async function loadClientsForInvoice() {
    try {
        const response = await fetch('/api/clients');
        if (response.ok) {
            const data = await response.json();
            invoiceClientSelect.innerHTML = '<option value="">Select Client</option>';
            data.clients.forEach(client => {
                const option = document.createElement('option');
                option.value = client.id;
                option.textContent = `${client.client_name}${client.pan_number ? ` (${client.pan_number})` : ''}`;
                invoiceClientSelect.appendChild(option);
            });
            updateInvoiceClientDetails();
        }
    } catch (error) {
        console.error('Error loading clients:', error);
    }
}

function resetInvoiceForm() {
    invoiceForm.reset();
    document.getElementById('invoiceEditId').value = '';
    document.getElementById('invoiceModalTitle').textContent = 'Create Invoice';
    document.getElementById('generateInvoiceBtn').textContent = 'Generate for Review';
    document.getElementById('invoiceWorkflowStatus').value = 'pending_review';
    invoiceClientSelect.innerHTML = '<option value="">Select Client</option>';
    document.getElementById('invoiceRequestToken').value =
        window.crypto && window.crypto.randomUUID
            ? window.crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
    updateInvoiceClientPreview(null);
    updateInvoiceTotals();
}

function updateInvoiceClientPreview(client) {
    const fields = {
        invoiceClientName: client ? client.client_name : '',
        invoiceClientEmail: client && client.email ? `Email: ${client.email}` : '',
        invoiceClientPan: client && client.pan_number ? `PAN: ${client.pan_number}` : '',
        invoiceClientPhone: client ? `Phone: ${client.phone}` : ''
    };
    Object.entries(fields).forEach(([id, value]) => {
        document.getElementById(id).textContent = value;
    });
    document.getElementById('invoiceClientPlaceholder').style.display = client ? 'none' : '';
}

async function updateInvoiceClientDetails() {
    const clientId = invoiceClientSelect.value;
    if (!clientId) {
        updateInvoiceClientPreview(null);
        return;
    }

    try {
        const response = await fetch(`/api/clients/${clientId}`);
        const client = await response.json();
        if (!response.ok) throw new Error(client.error || 'Unable to load client billing details.');
        updateInvoiceClientPreview(client);
    } catch (error) {
        console.error('Error loading invoice client details:', error);
        updateInvoiceClientPreview(null);
        document.getElementById('invoiceClientPlaceholder').textContent = error.message;
    }
}

function updateInvoiceTotals() {
    const amount = Number(document.getElementById('invoiceAmount').value);
    const discountType = document.getElementById('invoiceDiscountType').value;
    const discountInput = document.getElementById('invoiceDiscountValue');
    document.getElementById('invoiceDiscountValueLabel').textContent =
        discountType === 'percentage' ? 'Discount Value (%)' : 'Discount Value (₹)';
    const discountValue = discountInput.value.trim() === '' ? 0 : Number(discountInput.value);
    const subtotal = Number.isFinite(amount) && amount > 0 ? amount : 0;
    let validationMessage = '';
    if (!Number.isFinite(discountValue) || discountValue < 0) {
        validationMessage = 'Discount cannot be negative.';
    } else if (discountType === 'percentage' && discountValue > 100) {
        validationMessage = 'Percentage discount cannot exceed 100%.';
    } else if (discountType === 'fixed' && discountValue > subtotal) {
        validationMessage = 'Fixed discount cannot exceed the invoice subtotal.';
    }
    discountInput.setCustomValidity(validationMessage);
    discountInput.max = discountType === 'percentage'
        ? '100'
        : subtotal > 0 ? subtotal.toFixed(2) : '';
    const discountAmount = !validationMessage && subtotal > 0
        ? Math.round(((discountType === 'percentage'
            ? subtotal * discountValue / 100
            : discountValue) + Number.EPSILON) * 100) / 100
        : 0;
    const total = subtotal - discountAmount;
    const receivedInput = document.getElementById('invoiceReceivedAmount');
    const received = Math.max(0, Number(receivedInput.value) || 0);
    receivedInput.max = total.toFixed(2);
    document.getElementById('invoiceSubtotalPreview').value = `₹${subtotal.toFixed(2)}`;
    document.getElementById('invoiceDiscountAmountPreview').value =
        `${validationMessage ? 'Invalid discount · ' : ''}-₹${discountAmount.toFixed(2)}`;
    document.getElementById('invoiceTotalPreview').value = `₹${total.toFixed(2)}`;
    document.getElementById('invoiceBalancePreview').value = `₹${Math.max(0, total - received).toFixed(2)}`;
}

// Open modal
function openModal(modal) {
    closeAllModals();
    modal.classList.remove('is-closing');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';
}

// Close all modals
function closeAllModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        if (modal.style.display === 'none') return;
        modal.classList.add('is-closing');
        window.setTimeout(() => {
            if (modal.classList.contains('is-closing')) {
                modal.style.display = 'none';
                modal.classList.remove('is-closing');
            }
        }, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 220);
    });
    document.body.style.overflow = 'auto';
}

// Load reports
function loadReports() {
    loadReportFinancialYears();
    // Simple chart visualization using CSS
    const monthlyChart = document.getElementById('monthlyChart');
    const statusChart = document.getElementById('statusChart');
    
    if (monthlyChart) {
        monthlyChart.innerHTML = `
            <div style="text-align: center; padding: 20px;">
                <h3 style="color: var(--primary); margin-bottom: 20px;">Monthly Performance</h3>
                <div style="display: flex; align-items: flex-end; justify-content: center; gap: 20px; height: 200px;">
                    <div style="display: flex; flex-direction: column; align-items: center;">
                        <div class="chart-bar" title="January performance" style="width: 40px; height: 120px; background: linear-gradient(135deg, #C90016, #E32636); border-radius: 5px;"></div>
                        <span style="margin-top: 10px;">Jan</span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: center;">
                        <div class="chart-bar" title="February performance" style="width: 40px; height: 160px; background: linear-gradient(135deg, #171717, #3B3B3B); border-radius: 5px;"></div>
                        <span style="margin-top: 10px;">Feb</span>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: center;">
                        <div class="chart-bar" title="March performance" style="width: 40px; height: 100px; background: linear-gradient(135deg, #A80012, #E32636); border-radius: 5px;"></div>
                        <span style="margin-top: 10px;">Mar</span>
                    </div>
                </div>
            </div>
        `;
    }
    
    if (statusChart) {
        const pending = allClients.filter(c => c.status === 'pending').length;
        const found = allClients.filter(c => c.status === 'found').length;
        const notFound = allClients.filter(c => c.status === 'not_found').length;
        const total = allClients.length;
        
        statusChart.innerHTML = `
            <div style="text-align: center; padding: 20px;">
                <h3 style="color: var(--primary); margin-bottom: 20px;">Case Status Distribution</h3>
                <div style="display: flex; flex-direction: column; gap: 15px; width: 100%;">
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span>Pending (${pending})</span>
                            <span>${total ? Math.round((pending/total)*100) : 0}%</span>
                        </div>
                        <div style="height: 20px; background-color: #f0f0f0; border-radius: 10px; overflow: hidden;">
                            <div class="chart-progress" style="--chart-width: ${total ? (pending/total)*100 : 0}%; height: 100%; background: linear-gradient(135deg, #C90016, #E32636);"></div>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span>Found (${found})</span>
                            <span>${total ? Math.round((found/total)*100) : 0}%</span>
                        </div>
                        <div style="height: 20px; background-color: #f0f0f0; border-radius: 10px; overflow: hidden;">
                            <div class="chart-progress" style="--chart-width: ${total ? (found/total)*100 : 0}%; height: 100%; background: linear-gradient(135deg, #171717, #555);"></div>
                        </div>
                    </div>
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                            <span>Not Found (${notFound})</span>
                            <span>${total ? Math.round((notFound/total)*100) : 0}%</span>
                        </div>
                        <div style="height: 20px; background-color: #f0f0f0; border-radius: 10px; overflow: hidden;">
                            <div class="chart-progress" style="--chart-width: ${total ? (notFound/total)*100 : 0}%; height: 100%; background: linear-gradient(135deg, #A80012, #E32636);"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
}

async function loadReportFinancialYears() {
    if (!currentUser || currentUser.role !== 'admin') return;
    try {
        const response = await fetch('/api/reports/financial-years');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load report financial years.');

        const selectedYear = reportFinancialYearSelect.value;
        const selectedReferralYear = referralFinancialYearSelect.value;
        reportFinancialYearSelect.replaceChildren();
        const allYearsOption = document.createElement('option');
        allYearsOption.value = 'all';
        allYearsOption.textContent = 'All Financial Years';
        reportFinancialYearSelect.appendChild(allYearsOption);
        data.financial_years.forEach(year => {
            const option = document.createElement('option');
            option.value = year.value;
            option.textContent = year.label;
            reportFinancialYearSelect.appendChild(option);
        });
        referralFinancialYearSelect.replaceChildren();
        const allReferralYearsOption = document.createElement('option');
        allReferralYearsOption.value = 'all';
        allReferralYearsOption.textContent = 'All Financial Years';
        referralFinancialYearSelect.appendChild(allReferralYearsOption);
        data.financial_years.forEach(year => {
            const option = document.createElement('option');
            option.value = year.value;
            option.textContent = year.label;
            referralFinancialYearSelect.appendChild(option);
        });
        reportFinancialYearSelect.value = data.financial_years.some(
            year => year.value === selectedYear
        ) ? selectedYear : 'all';
        referralFinancialYearSelect.value = data.financial_years.some(
            year => year.value === selectedReferralYear
        ) ? selectedReferralYear : 'all';
        await loadReportSummary();
        await loadReportRemarks();
        await loadReferralReport();
    } catch (error) {
        console.error('Error loading report financial years:', error);
        alert(error.message || 'Unable to load report financial years.');
    }
}

async function loadReferralReport() {
    if (!currentUser || currentUser.role !== 'admin') return;
    const requestId = ++referralReportRequestId;
    const errorElement = document.getElementById('referralReportError');
    const referralsBody = document.getElementById('referralReportTableBody');
    const yearSummaryBody = document.getElementById('referralYearSummaryBody');
    errorElement.hidden = true;
    try {
        const params = new URLSearchParams({
            financial_year: referralFinancialYearSelect.value || 'all',
            client: referralClientSearch.value.trim()
        });
        const response = await fetch(`/api/referrals?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load referral report.');
        if (requestId !== referralReportRequestId) return;

        document.getElementById('referralTotalReferrers').textContent =
            Number(data.summary.total_referring_clients).toLocaleString('en-IN');
        document.getElementById('referralTotalReferred').textContent =
            Number(data.summary.total_referred_clients).toLocaleString('en-IN');
        const topClient = data.summary.most_referrals_by_client;
        document.getElementById('referralTopClient').textContent = topClient
            ? `${topClient.client_name} (${topClient.referral_count})`
            : '—';

        yearSummaryBody.replaceChildren();
        if (!data.summary.financial_year_referrals.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 2;
            cell.className = 'remarks-empty';
            cell.textContent = 'No referrals match the selected filters.';
            row.appendChild(cell);
            yearSummaryBody.appendChild(row);
        } else {
            data.summary.financial_year_referrals.forEach(year => {
                const row = document.createElement('tr');
                const yearCell = document.createElement('td');
                const countCell = document.createElement('td');
                yearCell.textContent = `FY ${year.financial_year}`;
                countCell.textContent = Number(year.referral_count).toLocaleString('en-IN');
                row.append(yearCell, countCell);
                yearSummaryBody.appendChild(row);
            });
        }

        referralsBody.replaceChildren();
        if (!data.referrals.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 5;
            cell.className = 'remarks-empty';
            cell.textContent = 'No referrals match the selected filters.';
            row.appendChild(cell);
            referralsBody.appendChild(row);
            return;
        }
        data.referrals.forEach(referral => {
            const row = document.createElement('tr');
            [
                referral.referrer_name,
                referral.referred_client_name,
                Number(referral.referral_count).toLocaleString('en-IN'),
                referral.referral_date,
                `FY ${referral.financial_year}`
            ].forEach(value => {
                const cell = document.createElement('td');
                cell.textContent = value || '';
                row.appendChild(cell);
            });
            referralsBody.appendChild(row);
        });
    } catch (error) {
        if (requestId !== referralReportRequestId) return;
        console.error('Error loading referral report:', error);
        errorElement.textContent = error.message || 'Unable to load referral report.';
        errorElement.hidden = false;
        [referralsBody, yearSummaryBody].forEach((body, index) => {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = index === 0 ? 5 : 2;
            cell.className = 'remarks-empty';
            cell.textContent = 'Unable to load referral records.';
            row.appendChild(cell);
            body.replaceChildren(row);
        });
    }
}

async function loadReportSummary() {
    if (!currentUser || currentUser.role !== 'admin') return;
    const requestId = ++reportSummaryRequestId;
    const summaryError = document.getElementById('reportSummaryError');
    summaryError.hidden = true;
    try {
        const selectedYear = encodeURIComponent(reportFinancialYearSelect.value || 'all');
        const response = await fetch(`/api/reports/summary?financial_year=${selectedYear}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load financial report totals.');
        if (requestId !== reportSummaryRequestId) return;

        const formatCurrency = amount => `INR ${Number(amount).toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        })}`;
        document.getElementById('reportTotalInvoiceAmount').textContent =
            formatCurrency(data.total_invoice_amount);
        document.getElementById('reportTotalPaidAmount').textContent =
            formatCurrency(data.total_paid_amount);
        document.getElementById('reportTotalPendingAmount').textContent =
            formatCurrency(data.total_pending_amount);
        document.getElementById('reportTotalGst').textContent =
            formatCurrency(data.total_gst);
        document.getElementById('reportTotalInvoices').textContent =
            Number(data.total_invoices).toLocaleString('en-IN');
        document.getElementById('reportTotalClients').textContent =
            Number(data.total_clients).toLocaleString('en-IN');
    } catch (error) {
        if (requestId !== reportSummaryRequestId) return;
        console.error('Error loading financial report totals:', error);
        [
            'reportTotalInvoiceAmount', 'reportTotalPaidAmount',
            'reportTotalPendingAmount', 'reportTotalGst',
            'reportTotalInvoices', 'reportTotalClients'
        ].forEach(id => {
            document.getElementById(id).textContent = 'Unavailable';
        });
        summaryError.textContent = error.message || 'Unable to load financial report totals.';
        summaryError.hidden = false;
    }
}

async function loadReportRemarks() {
    if (!currentUser || currentUser.role !== 'admin') return;
    const requestId = ++reportRemarksRequestId;
    const tableBody = document.getElementById('reportRemarksTableBody');
    const errorElement = document.getElementById('reportRemarksError');
    errorElement.hidden = true;
    tableBody.innerHTML = '<tr><td colspan="7" class="remarks-empty">Loading staff remarks...</td></tr>';
    try {
        const selectedYear = encodeURIComponent(reportFinancialYearSelect.value || 'all');
        const response = await fetch(`/api/reports/remarks?financial_year=${selectedYear}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load staff remarks.');
        if (requestId !== reportRemarksRequestId) return;

        tableBody.replaceChildren();
        if (!data.remarks.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 7;
            cell.className = 'remarks-empty';
            cell.textContent = 'No staff remarks are associated with this financial year.';
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }
        data.remarks.forEach(remark => {
            const row = document.createElement('tr');
            const values = [
                remark.client_name,
                (remark.invoice_numbers || []).join(', ') || '-',
                remark.staff_name,
                remark.remark_date,
                remark.remark_time,
                remark.category
            ];
            values.forEach(value => {
                const cell = document.createElement('td');
                cell.textContent = value || '';
                row.appendChild(cell);
            });
            const remarkCell = document.createElement('td');
            remarkCell.className = 'remark-description';
            addRemarkText(remarkCell, remark.remark, true);
            row.appendChild(remarkCell);
            tableBody.appendChild(row);
        });
    } catch (error) {
        if (requestId !== reportRemarksRequestId) return;
        console.error('Error loading report staff remarks:', error);
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = 'remarks-empty';
        cell.textContent = error.message || 'Unable to load staff remarks.';
        row.appendChild(cell);
        tableBody.replaceChildren(row);
        errorElement.textContent = error.message || 'Unable to load staff remarks.';
        errorElement.hidden = false;
    }
}

async function downloadReport(format, button) {
    if (!currentUser || currentUser.role !== 'admin') return;
    button.disabled = true;
    try {
        const selectedYear = encodeURIComponent(reportFinancialYearSelect.value || 'all');
        const response = await fetch(
            `/api/reports/export/${format}?financial_year=${selectedYear}`
        );
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `Unable to export the ${format.toUpperCase()} report.`);
        }

        const blob = await response.blob();
        const link = document.createElement('a');
        const downloadUrl = URL.createObjectURL(blob);
        const disposition = response.headers.get('Content-Disposition') || '';
        const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ||
            `TaxSecure_Report_${reportFinancialYearSelect.value === 'all'
                ? 'All_Years'
                : `FY_${reportFinancialYearSelect.value}`}.${format === 'excel' ? 'xlsx' : 'pdf'}`;
        link.href = downloadUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    } catch (error) {
        console.error(`Error exporting ${format.toUpperCase()} report:`, error);
        alert(error.message || `Unable to export the ${format.toUpperCase()} report.`);
    } finally {
        button.disabled = false;
    }
}

async function downloadReferralReport(format, button) {
    if (!currentUser || currentUser.role !== 'admin') return;
    button.disabled = true;
    try {
        const params = new URLSearchParams({
            financial_year: referralFinancialYearSelect.value || 'all',
            client: referralClientSearch.value.trim()
        });
        const response = await fetch(`/api/referrals/export/${format}?${params}`);
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `Unable to export the referral ${format.toUpperCase()} report.`);
        }

        const blob = await response.blob();
        const link = document.createElement('a');
        const downloadUrl = URL.createObjectURL(blob);
        const disposition = response.headers.get('Content-Disposition') || '';
        const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ||
            `TaxSecure_Referral_Report.${format === 'excel' ? 'xlsx' : 'pdf'}`;
        link.href = downloadUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    } catch (error) {
        console.error(`Error exporting referral ${format.toUpperCase()} report:`, error);
        alert(error.message || `Unable to export the referral ${format.toUpperCase()} report.`);
    } finally {
        button.disabled = false;
    }
}

// Edit task
async function editTask(taskId) {
    const task = allTasks.find(t => t.id === taskId);
    if (!task) return;
    
    document.getElementById('taskTitle').value = task.title;
    document.getElementById('taskDescription').value = task.description;
    document.getElementById('taskPriority').value = task.priority;
    document.getElementById('taskStatus').value = task.status;
    document.getElementById('taskDueDate').value = task.due_date;
    
    await loadStaffForTaskAssignment();
    await loadClientsForTaskAssignment();
    
    document.getElementById('taskAssignTo').value = task.assigned_to_id;
    if (task.client_id) {
        document.getElementById('taskClient').value = task.client_id;
    }
    
    const formTitle = document.querySelector('#taskModal .modal-header h3');
    formTitle.textContent = 'Edit Task';
    
    const originalSubmit = taskForm.onsubmit;
    taskForm.onsubmit = async (e) => {
        e.preventDefault();
        
        const formData = new FormData(taskForm);
        const taskData = {
            title: formData.get('title'),
            description: formData.get('description'),
            assigned_to: parseInt(formData.get('assigned_to')),
            client_id: formData.get('client_id') || null,
            priority: formData.get('priority'),
            status: formData.get('status'),
            due_date: formData.get('due_date') || null
        };
        
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(taskData)
            });
            
            const data = await response.json();
            
            if (data.success) {
                alert('Task updated successfully!');
                closeAllModals();
                taskForm.reset();
                taskForm.onsubmit = originalSubmit;
                loadTaskData();
            } else {
                alert('Error updating task: ' + (data.message || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error updating task:', error);
            alert('Error updating task. Please try again.');
        }
    };
    
    openModal(taskModal);
}

// Delete task
async function deleteTask(taskId) {
    if (!confirm('Are you sure you want to delete this task?')) return;
    
    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Task deleted successfully!');
            loadTaskData();
        } else {
            alert('Error deleting task: ' + (data.message || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error deleting task:', error);
        alert('Error deleting task. Please try again.');
    }
}

// Client operations
async function editClient(clientId) {
    const client = allClients.find(c => c.id === clientId);
    if (!client) return;

    resetClientForm();
    clientForm.dataset.clientId = String(client.id);
    populateReferrerOptions(client.referred_by_id || '', client.referred_by_name || '');
    // Populate form with client data
    document.getElementById('clientName').value = client.client_name;
    document.getElementById('clientEmail').value = client.email || '';
    document.getElementById('panNumber').value = client.pan_number || '';
    document.getElementById('clientPassword').value = '';
    document.getElementById('clientPassword').required = false;
    document.getElementById('clientPhone').value = client.phone;
    document.getElementById('clientStatus').value = client.status;
    
    // Load staff for assignment
    await loadStaffForAssignment();
    
    // Set assigned staff if exists
    const assignedStaff = allStaff.find(s => s.username === client.assigned_to);
    if (assignedStaff) {
        document.getElementById('assignStaff').value = assignedStaff.id;
    }
    
    // Change form to update mode
    document.querySelector('#addClientModal .modal-header h3').textContent = 'Edit Client';
    document.getElementById('saveClientBtn').textContent = 'Save Changes';
    openModal(addClientModal);
}

async function deleteClient(clientId) {
    if (currentUser.role !== 'admin') {
        alert('Admin access required to delete clients.');
        return;
    }

    if (!confirm('Are you sure you want to delete this client?')) return;
    
    try {
        const response = await fetch(`/api/clients/${clientId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert('Client deleted successfully!');
            loadDashboardData();
        } else {
            alert('Error deleting client: ' + (data.message || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error deleting client:', error);
        alert('Error deleting client. Please try again.');
    }
}

async function openClientRemark(clientId) {
    if (!currentUser || !['admin', 'staff'].includes(currentUser.role)) return;

    const client = allClients.find(item => item.id === clientId);
    if (!client) return;

    document.getElementById('remarkClientName').textContent = client.client_name;
    document.getElementById('remarkClientPan').textContent = client.pan_number || 'Not provided';
    document.getElementById('remarkCategory').value = 'ITR Return Pending';
    document.getElementById('remarkText').value = '';
    document.getElementById('clientRemarkHistory').replaceChildren();
    document.getElementById('remarkError').textContent = '';
    remarkForm.dataset.clientId = clientId;
    delete remarkForm.dataset.remarkId;
    document.getElementById('saveRemarkBtn').textContent = 'Add Remark';
    document.getElementById('cancelRemarkEditBtn').hidden = true;
    document.getElementById('saveRemarkBtn').disabled = true;
    openModal(remarkModal);

    try {
        const response = await fetch(`/api/clients/${clientId}/remark`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Unable to load this client remark.');
        }

        renderClientRemarkHistory(data.remarks || []);
    } catch (error) {
        console.error('Error loading client remark:', error);
        document.getElementById('remarkError').textContent = error.message;
    } finally {
        document.getElementById('saveRemarkBtn').disabled = false;
    }
}

function renderClientRemarkHistory(remarks) {
    const history = document.getElementById('clientRemarkHistory');
    history.replaceChildren();
    if (!remarks.length) {
        const empty = document.createElement('p');
        empty.textContent = 'No notes have been added for this client yet.';
        history.appendChild(empty);
        return;
    }

    remarks.forEach(remark => {
        const article = document.createElement('article');
        article.className = 'client-remark-entry';
        const heading = document.createElement('div');
        heading.className = 'client-remark-entry-heading';
        const author = document.createElement('strong');
        const roleLabel = remark.author_role === 'admin' ? 'Admin' : 'Staff';
        author.textContent = `${remark.author_name} (${roleLabel})`;
        const timestamp = document.createElement('time');
        timestamp.textContent = remark.created_at || `${remark.remark_date} ${remark.remark_time}`;
        if (remark.updated_at && remark.updated_at !== timestamp.textContent) {
            timestamp.title = `Last updated ${remark.updated_at}`;
        }
        heading.append(author, timestamp);

        const category = document.createElement('span');
        category.className = 'client-remark-category';
        category.textContent = remark.category;
        const text = document.createElement('p');
        text.textContent = remark.text;
        article.append(heading, category, text);

        if (currentUser && remark.author_id === Number(currentUser.id)) {
            const editButton = document.createElement('button');
            editButton.type = 'button';
            editButton.className = 'action-btn edit client-remark-edit';
            editButton.innerHTML = '<i class="fas fa-edit"></i> Edit';
            editButton.addEventListener('click', () => editClientRemark(remark));
            article.appendChild(editButton);
        }
        history.appendChild(article);
    });
}

function editClientRemark(remark) {
    remarkForm.dataset.remarkId = remark.id;
    document.getElementById('remarkCategory').value = remark.category;
    document.getElementById('remarkText').value = remark.text;
    document.getElementById('saveRemarkBtn').textContent = 'Update Remark';
    document.getElementById('cancelRemarkEditBtn').hidden = false;
    document.getElementById('remarkError').textContent = '';
}

function cancelClientRemarkEdit() {
    delete remarkForm.dataset.remarkId;
    document.getElementById('remarkCategory').value = 'ITR Return Pending';
    document.getElementById('remarkText').value = '';
    document.getElementById('saveRemarkBtn').textContent = 'Add Remark';
    document.getElementById('cancelRemarkEditBtn').hidden = true;
    document.getElementById('remarkError').textContent = '';
}

async function handleRemarkSubmit(event) {
    event.preventDefault();
    const clientId = remarkForm.dataset.clientId;
    const submitButton = document.getElementById('saveRemarkBtn');
    const errorMessage = document.getElementById('remarkError');
    submitButton.disabled = true;
    errorMessage.textContent = '';

    try {
        const remarkId = remarkForm.dataset.remarkId;
        const response = await fetch(
            `/api/clients/${clientId}/remark${remarkId ? `/${remarkId}` : ''}`,
            {
                method: remarkId ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    category: document.getElementById('remarkCategory').value,
                    remark: document.getElementById('remarkText').value
                })
            }
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Unable to save this remark.');
        }

        if (remarkId) {
            await loadClientRemarkHistory(clientId);
            cancelClientRemarkEdit();
        } else {
            document.getElementById('remarkText').value = '';
            document.getElementById('remarkCategory').value = 'ITR Return Pending';
            await loadClientRemarkHistory(clientId);
        }
        await loadRemarksData();
        alert('Remark saved successfully.');
    } catch (error) {
        console.error('Error saving client remark:', error);
        errorMessage.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function loadClientRemarkHistory(clientId) {
    const response = await fetch(`/api/clients/${clientId}/remark`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to refresh this client’s notes.');
    renderClientRemarkHistory(data.remarks || []);
}

function messageOnWhatsApp(phone) {
    // Remove any non-digit characters
    const cleanPhone = phone.replace(/\D/g, '');
    const message = "Hello, this is regarding your income tax documentation.";
    const url = `https://wa.me/${cleanPhone}?text=${encodeURIComponent(message)}`;
    window.open(url, '_blank');
}

async function createInvoiceForClient(clientId) {
    if (currentUser.role !== 'admin') {
        const client = allClients.find(item => item.id === clientId);
        if (!client) return;
        switchTab('invoices');
        invoiceSearch.value = client.client_name;
        renderInvoicesTable(allInvoices);
        return;
    }

    switchTab('invoices');
    resetInvoiceForm();
    await loadClientsForInvoice();
    document.getElementById('invoiceClient').value = clientId;
    await updateInvoiceClientDetails();
    openModal(invoiceModal);
}

// Staff operations
function editStaff(staffId) {
    const staffMember = allStaff.find(staff => staff.id === staffId);
    if (!staffMember || currentUser.role !== 'admin') return;

    document.getElementById('staffModalTitle').textContent = 'Edit Staff Account';
    document.getElementById('staffId').value = staffMember.id;
    document.getElementById('staffFullName').value = staffMember.full_name || '';
    const emailInput = document.getElementById('staffEmail');
    const staffEmail = staffMember.email || staffMember.username;
    emailInput.value = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(staffEmail) ? staffEmail : '';
    emailInput.required = false;
    document.getElementById('staffContact').value = staffMember.contact_number || '';
    document.getElementById('staffPassword').value = '';
    document.getElementById('staffConfirmPassword').value = '';
    document.getElementById('staffPassword').required = false;
    document.getElementById('staffConfirmPassword').required = false;
    document.getElementById('staffPasswordRequired').textContent = '(leave blank to keep current)';
    document.getElementById('staffConfirmRequired').textContent = '';
    document.getElementById('saveStaffBtn').textContent = 'Save Staff Account';
    document.getElementById('staffFormError').textContent = '';
    openModal(staffModal);
}

function resetStaffForm() {
    staffForm.reset();
    document.getElementById('staffId').value = '';
    document.getElementById('staffModalTitle').textContent = 'Add Staff Account';
    document.getElementById('staffEmail').required = true;
    document.getElementById('staffPassword').required = true;
    document.getElementById('staffConfirmPassword').required = true;
    document.getElementById('staffPasswordRequired').textContent = '*';
    document.getElementById('staffConfirmRequired').textContent = '*';
    document.getElementById('saveStaffBtn').textContent = 'Create Staff Account';
    document.getElementById('staffFormError').textContent = '';
}

async function handleStaffSubmit(event) {
    event.preventDefault();
    if (currentUser.role !== 'admin') return;

    const staffId = document.getElementById('staffId').value;
    const password = document.getElementById('staffPassword').value;
    const confirmPassword = document.getElementById('staffConfirmPassword').value;
    const errorElement = document.getElementById('staffFormError');
    const submitButton = document.getElementById('saveStaffBtn');
    errorElement.textContent = '';

    if ((!staffId || password) && password.length < 8) {
        errorElement.textContent = 'Password must be at least 8 characters.';
        return;
    }
    if (password !== confirmPassword) {
        errorElement.textContent = 'Passwords do not match.';
        return;
    }

    const staffData = {
        full_name: document.getElementById('staffFullName').value.trim(),
        contact_number: document.getElementById('staffContact').value.trim()
    };
    const email = document.getElementById('staffEmail').value.trim();
    if (!staffId || email) staffData.email = email;
    if (password) {
        staffData.password = password;
        staffData.confirm_password = confirmPassword;
    }

    submitButton.disabled = true;
    try {
        const response = await fetch(staffId ? `/api/staff/${staffId}` : '/api/staff/add', {
            method: staffId ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(staffData)
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Unable to save staff account.');
        }

        closeAllModals();
        resetStaffForm();
        await loadStaffData();
        alert(data.message);
    } catch (error) {
        console.error('Error saving staff account:', error);
        errorElement.textContent = error.message;
    } finally {
        submitButton.disabled = false;
    }
}

async function loadStaffData() {
    const response = await fetch('/api/staff');
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || 'Unable to load staff accounts.');
    }
    allStaff = data.staff;
    renderStaffTable(allStaff);
}

async function setStaffActive(staffId, isActive) {
    if (currentUser.role !== 'admin') return;
    const staffMember = allStaff.find(staff => staff.id === staffId);
    if (!staffMember) return;
    const action = isActive ? 'activate' : 'deactivate';
    if (!confirm(`Are you sure you want to ${action} ${staffMember.full_name || staffMember.username}?`)) return;

    try {
        const response = await fetch(`/api/staff/${staffId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: isActive })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `Unable to ${action} staff account.`);
        await loadStaffData();
    } catch (error) {
        console.error(`Error attempting to ${action} staff:`, error);
        alert(error.message);
    }
}

async function deleteStaff(staffId) {
    if (currentUser.role !== 'admin') return;
    if (!confirm('Are you sure you want to delete this staff member?')) return;

    try {
        const response = await fetch(`/api/staff/${staffId}`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (!response.ok) {
            alert('Error deleting staff member: ' + (data.error || 'Unknown error'));
            return;
        }

        allStaff = allStaff.filter(staffMember => staffMember.id !== staffId);
        renderStaffTable(allStaff);
        alert('Staff member deleted successfully!');
    } catch (error) {
        console.error('Error deleting staff member:', error);
        alert('Error deleting staff member. Please try again.');
    }
}

// Invoice operations
async function deleteInvoice(invoiceId) {
    if (currentUser.role !== 'admin') return;
    pendingInvoiceDeleteId = invoiceId;
    openModal(document.getElementById('deleteInvoiceModal'));
}

function cancelInvoiceDelete() {
    pendingInvoiceDeleteId = null;
    closeAllModals();
}

async function confirmInvoiceDelete() {
    if (currentUser.role !== 'admin' || pendingInvoiceDeleteId === null) return;
    const invoiceId = pendingInvoiceDeleteId;
    const deleteButton = document.getElementById('confirmDeleteInvoiceBtn');
    deleteButton.disabled = true;
    try {
        const response = await fetch(`/api/invoices/${invoiceId}`, { method: 'DELETE' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to delete invoice.');

        pendingInvoiceDeleteId = null;
        closeAllModals();
        allInvoices = allInvoices.filter(invoice => invoice.id !== invoiceId);
        renderInvoicesTable(allInvoices);
        await loadClientYearWiseData();
        alert('Invoice deleted successfully.');
    } catch (error) {
        console.error('Error deleting invoice:', error);
        alert(error.message || 'Error deleting invoice. Please try again.');
    } finally {
        deleteButton.disabled = false;
    }
}

async function viewInvoice(invoiceId, canEditStatus = false) {
    try {
        const response = await fetch(`/api/invoices/${invoiceId}`);
        const invoice = await response.json();
        if (!response.ok) throw new Error(invoice.error || 'Unable to load invoice details.');

        const content = document.getElementById('invoiceDetailsContent');
        content.innerHTML = '';
        const table = document.createElement('table');
        const rows = [
            ['Invoice Number', invoice.invoice_number],
            ['Invoice Date', invoice.date],
            ['Client Name', invoice.client_name],
            ['Email', invoice.client_email],
            ['PAN Number', invoice.client_pan_number],
            ['Phone', invoice.client_phone],
            ['Service', invoice.service_description],
            ['Subtotal', `₹${Number(invoice.amount).toFixed(2)}`],
            [invoice.discount_label, `-₹${Number(invoice.discount_amount || 0).toFixed(2)}`],
            ['Grand Total', `₹${Number(invoice.total).toFixed(2)}`],
            ['Received Amount', `₹${Number(invoice.received_amount || 0).toFixed(2)}`],
            ['Balance Amount', `₹${Number(invoice.balance_amount || 0).toFixed(2)}`],
            ['Payment Status', invoice.status],
            ['Approval Status', (invoice.workflow_status || 'approved').replaceAll('_', ' ')],
            ['WhatsApp Delivery', (invoice.delivery_status || 'legacy_unknown').replaceAll('_', ' ')]
        ];
        rows.forEach(([label, value]) => {
            const row = document.createElement('tr');
            const heading = document.createElement('th');
            heading.textContent = label;
            const cell = document.createElement('td');
            cell.textContent = value;
            row.append(heading, cell);
            table.appendChild(row);
        });
        content.appendChild(table);

        const isAdmin = currentUser.role === 'admin';
        const statusEditor = document.getElementById('invoiceStatusEditor');
        const saveStatusButton = document.getElementById('saveInvoiceStatusBtn');
        statusEditor.style.display = canEditStatus && isAdmin ? '' : 'none';
        saveStatusButton.style.display = canEditStatus && isAdmin ? '' : 'none';
        document.getElementById('invoiceDetailsStatus').value = invoice.status;
        document.getElementById('invoiceDetailsModal').dataset.invoiceId = invoice.id;
        openModal(document.getElementById('invoiceDetailsModal'));
    } catch (error) {
        console.error('Error loading invoice details:', error);
        alert(error.message);
    }
}

function editInvoice(invoiceId) {
    if (currentUser.role === 'admin') openInvoiceForEditing(invoiceId);
}

async function openInvoiceForEditing(invoiceId) {
    try {
        const response = await fetch(`/api/invoices/${invoiceId}`);
        const invoice = await response.json();
        if (!response.ok) throw new Error(invoice.error || 'Unable to load invoice for editing.');
        if (!['draft', 'pending_review'].includes(invoice.workflow_status)) {
            throw new Error('Only invoices awaiting review can be edited.');
        }

        await loadClientsForInvoice();
        document.getElementById('invoiceEditId').value = invoice.id;
        document.getElementById('invoiceModalTitle').textContent = 'Edit Invoice';
        document.getElementById('generateInvoiceBtn').textContent = 'Save Changes & Review';
        document.getElementById('invoiceWorkflowStatus').value = 'pending_review';
        document.getElementById('invoiceServiceDescription').value = invoice.service_description;
        document.getElementById('invoiceAmount').value = Number(invoice.amount).toFixed(2);
        document.getElementById('invoiceDiscountType').value = invoice.discount_type || 'percentage';
        document.getElementById('invoiceDiscountValue').value =
            Number(invoice.discount_value || 0).toFixed(2);
        document.getElementById('invoiceReceivedAmount').value = Number(invoice.received_amount || 0).toFixed(2);
        document.getElementById('invoiceStatus').value = invoice.status;
        invoiceClientSelect.value = String(invoice.client_id);
        await updateInvoiceClientDetails();
        updateInvoiceTotals();
        openModal(invoiceModal);
    } catch (error) {
        console.error('Error opening invoice for editing:', error);
        alert(error.message);
    }
}

async function reviewInvoice(invoiceId) {
    try {
        const response = await fetch(`/api/invoices/${invoiceId}`);
        const invoice = await response.json();
        if (!response.ok) throw new Error(invoice.error || 'Unable to load invoice review.');

        currentReviewInvoice = invoice;
        document.getElementById('invoiceReviewHeading').textContent =
            `${invoice.invoice_number} · ${invoice.client_name}`;
        const summary = document.getElementById('invoiceReviewSummary');
        summary.replaceChildren();
        const discountType = invoice.discount_type || 'percentage';
        const discountValue = Number(invoice.discount_value || 0);
        [
            ['Client details', invoice.client_name],
            ['Email', invoice.client_email],
            ['Phone', invoice.client_phone],
            ['PAN', invoice.client_pan_number],
            ['Invoice number', invoice.invoice_number],
            ['Invoice date', invoice.date],
            ['Invoice items', invoice.service_description],
            ['Subtotal', `₹${Number(invoice.subtotal ?? invoice.amount).toFixed(2)}`],
            ['Discount percentage', discountType === 'percentage' ? `${discountValue}%` : 'Not applicable (fixed discount)'],
            ['Discount amount', `-₹${Number(invoice.discount_amount || 0).toFixed(2)}`],
            ['Final payable amount', `₹${Number(invoice.total).toFixed(2)}`],
            ['Received amount', `₹${Number(invoice.received_amount || 0).toFixed(2)}`],
            ['Balance amount', `₹${Number(invoice.balance_amount || 0).toFixed(2)}`],
            ['Approval', (invoice.workflow_status || 'approved').replaceAll('_', ' ')],
            ['WhatsApp delivery', (invoice.delivery_status || 'legacy_unknown').replaceAll('_', ' ')]
        ].forEach(([label, value]) => {
            const item = document.createElement('div');
            const heading = document.createElement('strong');
            heading.textContent = label;
            const detail = document.createElement('span');
            detail.textContent = value || '—';
            item.append(heading, detail);
            summary.appendChild(item);
        });

        const admin = currentUser.role === 'admin';
        const editable = admin && ['draft', 'pending_review'].includes(invoice.workflow_status);
        const editButton = document.getElementById('editReviewInvoiceBtn');
        editButton.hidden = !editable;
        const manualSentButton = document.getElementById('markManualInvoiceSentBtn');
        manualSentButton.hidden = !admin || invoice.workflow_status !== 'approved' ||
            invoice.delivery_status !== 'manual_required';
        const sendButton = document.getElementById('approveShareInvoiceBtn');
        sendButton.hidden = !admin || !['draft', 'pending_review', 'approved'].includes(invoice.workflow_status);
        sendButton.disabled = ['sending', 'sent', 'legacy_unknown'].includes(invoice.delivery_status);
        if (invoice.workflow_status !== 'approved') {
            sendButton.textContent = 'Approve & Send on WhatsApp';
        } else if (invoice.delivery_status === 'manual_required') {
            sendButton.textContent = 'Open WhatsApp & Download PDF';
        } else if (invoice.delivery_status === 'failed') {
            sendButton.textContent = 'Retry WhatsApp Delivery';
        } else if (invoice.delivery_status === 'sending') {
            sendButton.textContent = 'Delivery Confirmation Pending';
        } else if (invoice.delivery_status === 'sent') {
            sendButton.textContent = 'Invoice Sent';
        } else if (invoice.delivery_status === 'legacy_unknown') {
            sendButton.textContent = 'Delivery History Unknown';
        } else {
            sendButton.textContent = 'Send on WhatsApp';
        }
        const note = document.getElementById('invoiceReviewNote');
        note.textContent = invoice.delivery_error
            ? `Previous delivery issue: ${invoice.delivery_error}`
            : invoice.workflow_status === 'approved'
                ? (invoice.delivery_status === 'sent'
                    ? 'WhatsApp delivery was confirmed.'
                    : invoice.delivery_status === 'sending'
                        ? 'WhatsApp accepted the document; delivery confirmation is pending.'
                        : '')
                : 'Review the complete PDF before approving and sharing this invoice.';
        document.getElementById('invoiceReviewPreview').src = `/api/invoices/${invoice.id}/preview`;
        const reviewModal = document.getElementById('invoiceReviewModal');
        openModal(reviewModal);
        requestAnimationFrame(() => {
            summary.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    } catch (error) {
        console.error('Error loading invoice review:', error);
        alert(error.message);
    }
}

async function approveAndShareInvoice(invoiceId = null) {
    if (currentUser.role !== 'admin') return;
    const invoice = invoiceId
        ? allInvoices.find(item => item.id === invoiceId) || { id: invoiceId }
        : currentReviewInvoice;
    if (!invoice) return;

    let chatWindow = null;
    if (invoice.workflow_status === 'approved' && invoice.delivery_status === 'failed' &&
        !confirm('WhatsApp previously reported a delivery failure. Retry sending this invoice?')) return;
    if (invoice.delivery_status === 'manual_required' ||
        invoice.workflow_status !== 'approved' ||
        invoice.delivery_status === 'failed') {
        chatWindow = window.open('about:blank', '_blank');
    }

    const button = document.getElementById('approveShareInvoiceBtn');
    button.disabled = true;
    const note = document.getElementById('invoiceReviewNote');
    note.textContent = '';
    try {
        let currentInvoice = invoice;
        if (currentInvoice.workflow_status !== 'approved') {
            const approveResponse = await fetch(`/api/invoices/${invoice.id}/approve`, { method: 'POST' });
            const approveData = await approveResponse.json();
            if (!approveResponse.ok) throw new Error(approveData.error || 'Unable to approve invoice.');
            currentInvoice = approveData.invoice;
        }

        const retry = currentInvoice.delivery_status === 'failed';
        const shareResponse = await fetch(`/api/invoices/${invoice.id}/share-whatsapp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(retry ? { retry: true } : {})
        });
        const shareData = await shareResponse.json();
        if (!shareResponse.ok) throw new Error(shareData.error || 'Unable to share invoice.');

        let completionNote;
        if (shareData.delivery_status === 'manual_required') {
            const download = document.createElement('a');
            download.href = shareData.download_url;
            download.download = `${currentInvoice.invoice_number}.pdf`;
            document.body.appendChild(download);
            download.click();
            download.remove();
            if (chatWindow) {
                chatWindow.location = shareData.whatsapp_url;
                chatWindow.focus();
            }
            completionNote = 'WhatsApp chat opened and the PDF downloaded. Attach the PDF to the chat to complete sharing; it has not been sent automatically.';
        } else {
            if (chatWindow) chatWindow.close();
            completionNote = 'WhatsApp accepted the PDF document. Delivery confirmation is pending.';
        }

        note.textContent = completionNote;
        try {
            const invoicesResponse = await fetch('/api/invoices');
            const invoicesData = await invoicesResponse.json();
            if (!invoicesResponse.ok) throw new Error(invoicesData.error || 'Invoice history could not be refreshed.');
            allInvoices = invoicesData.invoices;
            renderInvoicesTable(allInvoices);
        } catch (refreshError) {
            console.error('Invoice action completed, but history could not be refreshed:', refreshError);
        }
        await reviewInvoice(invoice.id);
        document.getElementById('invoiceReviewNote').textContent = completionNote;
    } catch (error) {
        if (chatWindow && !chatWindow.closed) chatWindow.close();
        console.error('Error approving or sharing invoice:', error);
        try {
            const invoicesResponse = await fetch('/api/invoices');
            const invoicesData = await invoicesResponse.json();
            if (invoicesResponse.ok) {
                allInvoices = invoicesData.invoices;
                renderInvoicesTable(allInvoices);
            }
            await reviewInvoice(invoice.id);
        } catch (refreshError) {
            console.error('Unable to refresh invoice delivery status:', refreshError);
        }
        note.textContent = error.message;
    } finally {
        button.disabled = false;
    }
}

async function markManualInvoiceSent() {
    if (currentUser.role !== 'admin' || !currentReviewInvoice) return;
    if (!confirm("Have you manually sent the downloaded invoice PDF in the client's WhatsApp chat?")) return;

    const button = document.getElementById('markManualInvoiceSentBtn');
    const note = document.getElementById('invoiceReviewNote');
    button.disabled = true;
    try {
        const response = await fetch(`/api/invoices/${currentReviewInvoice.id}/mark-manual-sent`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed: true })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to record the manual WhatsApp delivery.');

        try {
            const invoicesResponse = await fetch('/api/invoices');
            const invoicesData = await invoicesResponse.json();
            if (!invoicesResponse.ok) throw new Error(invoicesData.error || 'Invoice history could not be refreshed.');
            allInvoices = invoicesData.invoices;
            renderInvoicesTable(allInvoices);
        } catch (refreshError) {
            console.error('Manual delivery was recorded, but history could not be refreshed:', refreshError);
        }
        await reviewInvoice(currentReviewInvoice.id);
        document.getElementById('invoiceReviewNote').textContent =
            'Manual WhatsApp delivery recorded based on your confirmation.';
    } catch (error) {
        console.error('Error recording manual invoice delivery:', error);
        note.textContent = error.message;
    } finally {
        button.disabled = false;
    }
}

async function saveInvoiceStatus() {
    if (currentUser.role !== 'admin') return;
    const modal = document.getElementById('invoiceDetailsModal');
    const invoiceId = modal.dataset.invoiceId;
    const button = document.getElementById('saveInvoiceStatusBtn');
    button.disabled = true;
    try {
        const response = await fetch(`/api/invoices/${invoiceId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: document.getElementById('invoiceDetailsStatus').value })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to update invoice status.');
        closeAllModals();
        const invoicesResponse = await fetch('/api/invoices');
        const invoicesData = await invoicesResponse.json();
        if (!invoicesResponse.ok) throw new Error(invoicesData.error || 'Invoice status saved, but the list could not be refreshed.');
        allInvoices = invoicesData.invoices;
        renderInvoicesTable(allInvoices);
    } catch (error) {
        console.error('Error updating invoice status:', error);
        alert(error.message);
    } finally {
        button.disabled = false;
    }
}

function printInvoice(invoiceId) {
    window.open(`/api/invoices/${invoiceId}/print`, '_blank', 'noopener');
}

function downloadInvoice(invoiceId) {
    try {
        const downloadUrl = `/api/invoices/${invoiceId}/pdf`;
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `invoice-${invoiceId}.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } catch (error) {
        console.error('Error downloading invoice:', error);
        alert('Failed to download invoice. Please try again.');
    }
}