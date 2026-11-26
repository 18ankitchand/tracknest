/* TrackNest premium module interactions. Uses existing session + CSRF helpers. */
let premiumCategories = [];
let premiumBudgets = [];
let premiumGoals = [];
let premiumNotifications = [];
let premiumNotificationIds = null;
let premiumNotificationPoll = null;
let premiumAlertAudio = null;

// Browser audio is permitted only after a user interaction on many devices.
function ringPremiumNotification(){
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if(!AudioContextClass) return;
    premiumAlertAudio = premiumAlertAudio || new AudioContextClass();
    if(premiumAlertAudio.state !== 'running') return;
    const now = premiumAlertAudio.currentTime;
    [0, 0.16].forEach((delay)=>{
      const oscillator=premiumAlertAudio.createOscillator();
      const gain=premiumAlertAudio.createGain();
      oscillator.type='sine';
      oscillator.frequency.value=delay===0?880:1175;
      gain.gain.setValueAtTime(0.0001,now+delay);
      gain.gain.exponentialRampToValueAtTime(0.12,now+delay+0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001,now+delay+0.15);
      oscillator.connect(gain).connect(premiumAlertAudio.destination);
      oscillator.start(now+delay);
      oscillator.stop(now+delay+0.16);
    });
  }catch(error){console.debug('Notification sound unavailable',error);}
}
document.addEventListener('pointerdown',()=>{
  const AudioContextClass=window.AudioContext || window.webkitAudioContext;
  if(!AudioContextClass) return;
  try {
    premiumAlertAudio=premiumAlertAudio || new AudioContextClass();
    if(premiumAlertAudio.state==='suspended') premiumAlertAudio.resume().catch(()=>{});
  }catch(error){console.debug('Audio initialization unavailable',error);}
},{once:true});
function startPremiumNotificationPolling(){
  if(premiumNotificationPoll) return;
  premiumNotificationPoll=window.setInterval(()=>{
    if(currentUser && document.visibilityState==='visible')
      loadPremiumNotifications().catch(()=>{});
  },30000);
}

let premiumAnalyticsData = null;
let premiumTransactionPage = 1;
let premiumTransactionPageSize = 10;
const premiumCharts = {};
const premiumMoney = n => 'Nrs ' + Number(n || 0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const $tn = id => document.getElementById(id);

async function premiumGet(url) {
  const response = await fetch(url,{credentials:'same-origin'});
  let result;
  try {result = await response.json();} catch {throw new Error('Unexpected server response.');}
  if(!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}
function premiumError(error){showAccountToast(error.message || 'Unable to save changes.','error');}
function premiumSuccess(message){showAccountToast(message,'success');}
async function loadPremiumModules(){
  try {
    // Recover missed current-month milestone alerts from older TrackNest
    // versions. This endpoint is idempotent and does not edit transactions.
    try { await authRequest('/api/notifications/sync/', {}); }
    catch(error) { console.warn('Budget alert reconciliation unavailable:', error.message); }
    await Promise.all([loadPremiumCategories(),loadPremiumNotifications(),loadPremiumAnalytics(),loadPremiumSettings()]);
    await Promise.all([loadPremiumBudgets(),loadPremiumGoals()]);
    renderPremiumCategorySelectors();
  } catch(error){console.error('Premium module loading failed', error);premiumError(error);}
}
async function loadPremiumSection(section){
  try {
    if(section==='income') await loadIncomeOverview();
  if(section==='expense') await loadSpendingOverview();
    if(section==='categories') await loadPremiumCategories();
    else if(section==='budget') {await loadPremiumCategories();await loadPremiumBudgets();}
    else if(section==='goals') await loadPremiumGoals();
    else if(section==='notifications') await loadPremiumNotifications();
    else if(section==='reports') await loadPremiumAnalytics();
  else if(section==='forecast') await loadExpenseForecast();
    else if(section==='settings') await loadPremiumSettings();
    else if(section==='profile') populatePremiumProfile();
  } catch(error) {premiumError(error);}
}
function renderPremiumCategorySelectors(){
  const select=$tn('tnBudgetCategory'); const keep=select.value;
  // The Expenses form has built-in categories, while custom Category rows may be empty.
  // Show both so users can budget existing/default expense categories without visiting Categories first.
  const known=premiumCategories.filter(c=>c.type==='expense');
  const categoryNames=[...new Set([
    ...Array.from($tn('expenseEntryCategory').options).map(option=>option.value).filter(Boolean),
    ...transactions.filter(t=>t.type==='expense').map(t=>t.category).filter(Boolean),
    ...known.map(c=>c.name)
  ])].sort((a,b)=>a.localeCompare(b));
  select.innerHTML='<option value="">Select category</option>'+categoryNames.map(name=>{
    const saved=known.find(c=>c.name.toLowerCase()===name.toLowerCase());
    const value=saved?String(saved.id):'name:'+name;
    return '<option value="'+escapeHtml(value)+'">'+escapeHtml(name)+'</option>';
  }).join('');
  if(keep && Array.from(select.options).some(option=>option.value===keep)) select.value=keep;
  const filter=$tn('tnTransactionCategoryFilter'), filterValue=filter.value;
  const names=[...new Set([...transactions.map(t=>t.category),...premiumCategories.map(c=>c.name)])].sort();
  filter.innerHTML='<option value="">All categories</option>'+names.map(x=>'<option>'+escapeHtml(x)+'</option>').join('');
  filter.value=filterValue;
  for(const kind of ['income','expense']){
    const el=$tn(kind+'FilterCategory'),previous=el.value;
    const names=[...new Set([
      ...transactions.filter(t=>t.type===kind).map(t=>t.category),
      ...premiumCategories.filter(c=>c.type===kind).map(c=>c.name)
    ])].sort();
    el.innerHTML='<option value="">All categories</option>'+names.map(name=>
      '<option>'+escapeHtml(name)+'</option>').join('');
    el.value=previous;
  }
  // Retain original common categories while allowing custom categories created by the user.
  for(const [kind,id] of [['income','incomeEntryCategory'],['expense','expenseEntryCategory']]){
    const el=$tn(id),previous=el.value, all=Array.from(el.options).map(o=>o.value);
    premiumCategories.filter(c=>c.type===kind).forEach(c=>{if(!all.includes(c.name))el.add(new Option(c.name,c.name));});
    if(previous)el.value=previous;
  }
  if($tn('txCategory'))premiumCategories.forEach(c=>{
    const el=$tn('txCategory');if(!Array.from(el.options).some(o=>o.value===c.name))el.add(new Option(c.name,c.name));
  });
}
async function loadPremiumCategories(){
  premiumCategories=(await premiumGet('/api/categories/')).categories;
  $tn('tnCategoryList').innerHTML = premiumCategories.length ? premiumCategories.map(c=>
    '<div class="tn-premium-list-item"><div><strong>'+escapeHtml(c.name)+'</strong><small>'+escapeHtml(c.type)+'</small></div><div>'+
    '<button class="edit-transaction-btn" onclick="editPremiumCategory('+c.id+')">Edit</button>'+
    '<button class="tn-delete-btn" onclick="deletePremiumCategory('+c.id+')">Delete</button></div></div>'
  ).join(''):'<p class="tn-premium-empty">No custom categories yet. Create one above.</p>';
  renderPremiumCategorySelectors();
}
function editPremiumCategory(id){
  const item=premiumCategories.find(c=>c.id===id);if(!item)return;
  $tn('tnCategoryId').value=item.id;$tn('tnCategoryName').value=item.name;$tn('tnCategoryType').value=item.type;
  $tn('tnCategoryName').focus();
}
function resetPremiumCategory(){$tn('tnCategoryForm').reset();$tn('tnCategoryId').value='';}
async function savePremiumCategory(event){
  event.preventDefault();const id=$tn('tnCategoryId').value;
  try{
    await authRequest('/api/categories/change/',{action:id?'edit':'create',id:id?Number(id):undefined,
      name:$tn('tnCategoryName').value,type:$tn('tnCategoryType').value});
    resetPremiumCategory();await loadPremiumCategories();premiumSuccess('Category saved.');
  }catch(e){premiumError(e);}
}
async function deletePremiumCategory(id){
  if(!confirm('Delete this category? Existing financial records keep their saved category name.'))return;
  try{await authRequest('/api/categories/change/',{action:'delete',id});await loadPremiumCategories();premiumSuccess('Category removed.');}
  catch(e){premiumError(e);}
}

async function loadPremiumBudgets(){
  const data=await premiumGet('/api/category-budgets/');
  premiumBudgets=data.budgets;
  $tn('tnCategoryBudgetList').innerHTML=premiumBudgets.length ? premiumBudgets.map(b=>{
    const pct=Math.min(100,Number(b.percentage));
    const color=b.percentage>=100?'#ef5261':b.percentage>=90?'#f5a04b':b.percentage>=70?'#f5c14a':'#23b477';
    return '<div class="tn-premium-tile"><h3>'+escapeHtml(b.category)+'</h3>'+
     '<div class="tn-tile-row"><small>Budget</small><strong>'+premiumMoney(b.limit)+'</strong></div>'+
     '<div class="tn-tile-row"><small>Spent</small><strong>'+premiumMoney(b.spent)+'</strong></div>'+
     '<div class="tn-tile-row"><small>Remaining</small><strong>'+premiumMoney(b.remaining)+'</strong></div>'+
     '<div class="tn-premium-progress"><div style="width:'+pct+'%;background:'+color+'"></div></div>'+
     '<div class="tn-tile-row"><small>'+Number(b.percentage).toFixed(1)+'% used</small><span>'+
     '<button class="edit-transaction-btn" onclick="editPremiumBudget('+b.id+')">Edit</button>'+
     '<button class="tn-delete-btn" onclick="deletePremiumBudget('+b.id+')">Delete</button></span></div></div>';
  }).join(''):'<p class="tn-premium-empty">No category budgets yet. Choose an expense category above, enter a monthly limit, and save your first category budget.</p>';
}
function editPremiumBudget(id){
  const b=premiumBudgets.find(x=>x.id===id);if(!b)return;
  $tn('tnCategoryBudgetId').value=b.id;$tn('tnBudgetCategory').value=b.category_id;
  $tn('tnBudgetAmount').value=b.limit;$tn('tnBudgetCategory').disabled=true;
  $tn('tnBudgetAmount').focus();
}
function resetPremiumCategoryBudget(){
  $tn('tnCategoryBudgetForm').reset();$tn('tnCategoryBudgetId').value='';$tn('tnBudgetCategory').disabled=false;
}
async function savePremiumCategoryBudget(e){
  e.preventDefault();const id=$tn('tnCategoryBudgetId').value;
  try{
    await authRequest('/api/category-budgets/change/',{action:id?'edit':'create',
      id:id?Number(id):undefined,
      category_id:$tn('tnBudgetCategory').value.startsWith('name:')?undefined:Number($tn('tnBudgetCategory').value),
      category_name:$tn('tnBudgetCategory').value.startsWith('name:')?$tn('tnBudgetCategory').value.slice(5):undefined,
      limit:$tn('tnBudgetAmount').value,month:trackNestToday().slice(0,7)+'-01'});
    resetPremiumCategoryBudget();await loadPremiumCategories();await loadPremiumBudgets();premiumSuccess('Category budget saved.');
  }catch(error){premiumError(error);}
}
async function deletePremiumBudget(id){
  if(!confirm('Remove this category budget? Existing transactions are not deleted.'))return;
  try{await authRequest('/api/category-budgets/change/',{action:'delete',id});
    await loadPremiumBudgets();premiumSuccess('Category budget removed.');}catch(e){premiumError(e);}
}

async function loadPremiumGoals(){
  premiumGoals=(await premiumGet('/api/goals/')).goals;
  $tn('tnGoalsList').innerHTML=premiumGoals.length?premiumGoals.map(g=>{
    const pct=g.target ? Math.min(100,100*g.saved/g.target):0;
    return '<div class="tn-premium-tile"><h3>'+escapeHtml(g.name)+'</h3>'+
      '<small>Target '+premiumMoney(g.target)+(g.deadline?' · '+escapeHtml(g.deadline):'')+'</small>'+
      '<div class="tn-premium-progress"><div style="width:'+pct+'%;background:#6557e9"></div></div>'+
      '<div class="tn-tile-row"><strong>'+premiumMoney(g.saved)+'</strong><small>'+pct.toFixed(0)+'% complete</small></div>'+
      '<div class="tn-tile-row"><input style="max-width:130px" id="tnContribute'+g.id+'" type="number" min=".01" step=".01" placeholder="Amount" aria-label="Contribution amount">'+
      '<button class="primary-btn" onclick="contributePremiumGoal('+g.id+')">Add savings</button></div>'+
      '<div class="tn-tile-row"><button class="edit-transaction-btn" onclick="editPremiumGoal('+g.id+')">Edit</button>'+
      '<button class="tn-delete-btn" onclick="deletePremiumGoal('+g.id+')">Delete</button></div></div>';
  }).join(''):'<p class="tn-premium-empty">No goals yet. Add a goal above.</p>';
}
function editPremiumGoal(id){
  const g=premiumGoals.find(x=>x.id===id);if(!g)return;
  $tn('tnGoalId').value=id;$tn('tnGoalName').value=g.name;
  $tn('tnGoalTarget').value=g.target;$tn('tnGoalDeadline').value=g.deadline||'';
  $tn('tnGoalName').focus();
}
function resetPremiumGoal(){$tn('tnGoalForm').reset();$tn('tnGoalId').value='';}
async function savePremiumGoal(e){
  e.preventDefault();const id=$tn('tnGoalId').value;
  try{await authRequest('/api/goals/change/',{action:id?'edit':'create',id:id?Number(id):undefined,
    name:$tn('tnGoalName').value,target:$tn('tnGoalTarget').value,deadline:$tn('tnGoalDeadline').value});
    resetPremiumGoal();await loadPremiumGoals();premiumSuccess('Savings goal saved.');}catch(e){premiumError(e);}
}
async function deletePremiumGoal(id){
  if(!confirm('Delete this goal and its saved contribution history?'))return;
  try{await authRequest('/api/goals/change/',{action:'delete',id});await loadPremiumGoals();premiumSuccess('Goal removed.');}
  catch(e){premiumError(e);}
}
async function contributePremiumGoal(id){
  const amount=$tn('tnContribute'+id).value;
  try{await authRequest('/api/goals/change/',{action:'contribute',id,amount});
    await loadPremiumGoals();premiumSuccess('Savings allocation recorded.');}catch(e){premiumError(e);}
}

async function loadPremiumNotifications(){
  const data=await premiumGet('/api/notifications/');
  premiumNotifications=data.notifications;
  const receivedIds = new Set(premiumNotifications.map(n=>n.id));
  const newlyReceived = premiumNotificationIds===null ? [] :
    premiumNotifications.filter(n=>!n.is_read && !premiumNotificationIds.has(n.id));
  premiumNotificationIds=receivedIds;
  const badge=$tn('tnNotificationBadge');
  if(badge){
    badge.hidden=!data.unread;
    badge.textContent=data.unread>99?'99+':String(data.unread);
    badge.setAttribute('aria-label',data.unread+' unread notifications');
  }
  if(newlyReceived.length){
    const bell=$tn('tnNotificationBell');
    if(bell){
      bell.classList.remove('tn-bell-ringing');
      void bell.offsetWidth;
      bell.classList.add('tn-bell-ringing');
    }
    ringPremiumNotification();
    showBudgetToast(newlyReceived[0].title+': '+newlyReceived[0].message);
  }
  startPremiumNotificationPolling();
  $tn('tnUnreadCount').textContent=data.unread?'('+data.unread+' unread)':'';
  $tn('tnNotificationList').innerHTML=premiumNotifications.length?premiumNotifications.map(n=>
    '<div class="tn-premium-list-item"><div><strong>'+escapeHtml(n.title)+(n.is_read?'':' ●')+'</strong>'+
    '<small>'+escapeHtml(n.message)+' · '+new Date(n.created_at).toLocaleString()+'</small></div>'+
    (n.is_read?'':'<button class="edit-transaction-btn" onclick="markPremiumNotification('+n.id+')">Mark read</button>')+'</div>'
  ).join(''):'<p class="tn-premium-empty">No budget alerts yet.</p>';
  const banner=$tn('tnDashboardAlerts');
  if(banner)banner.innerHTML=premiumNotifications.filter(n=>!n.is_read).slice(0,2).map(n=>
    '<div class="tn-premium-tile"><strong>'+escapeHtml(n.title)+'</strong><p>'+escapeHtml(n.message)+'</p></div>').join('');
}
async function markPremiumNotification(id){
  try{await authRequest('/api/notifications/read/',id===null?{all:true}:{id});
    await loadPremiumNotifications();}catch(e){premiumError(e);}
}
async function loadPremiumSettings(){
  const data=await premiumGet('/api/preferences/');
  $tn('tnSettingsTheme').value=data.theme;
  $tn('tnSettingsEmail').checked=data.email_alerts_enabled;
  $tn('tnSettingsCurrency').value=data.currency;
  applyPremiumTheme(data.theme);
}
function applyPremiumTheme(theme){
  $tn('appScreen').classList.toggle('tn-dark',theme==='dark');
}
async function savePremiumSettings(event){
  event.preventDefault();
  try{await authRequest('/api/preferences/change/',{theme:$tn('tnSettingsTheme').value,
      currency:'NPR',email_alerts_enabled:$tn('tnSettingsEmail').checked});
    applyPremiumTheme($tn('tnSettingsTheme').value);premiumSuccess('Preferences saved.');}
  catch(e){premiumError(e);}
}
function populatePremiumProfile(){
  $tn('tnProfileName').value=currentUser.name||'';
  $tn('tnProfileEmail').value=currentUser.email||'';
  $tn('tnProfilePhone').value=currentUser.phone||'';
}
async function savePremiumProfile(event){
  event.preventDefault();
  try{const result=await authRequest('/api/profile/change/',{
    name:$tn('tnProfileName').value,phone:$tn('tnProfilePhone').value});
    currentUser.name=result.name;currentUser.phone=result.phone;
    $tn('displayUserName').textContent=result.name;$tn('tnWelcomeName').textContent=result.name;
    premiumSuccess('Profile updated.');}catch(e){premiumError(e);}
}

async function changePremiumPassword(event){
  event.preventDefault();
  const oldPassword=$tn('tnOldPassword').value, newPassword=$tn('tnNewPassword').value;
  try{
    await authRequest('/api/profile/password/',{current_password:oldPassword,new_password:newPassword});
    event.currentTarget.reset();premiumSuccess('Password updated. Your session remains active.');
  }catch(error){premiumError(error);}
}
async function requestPremiumEmailChange(event){
  event.preventDefault();
  try{
    const result=await authRequest('/api/profile/request-email/',{
      new_email:$tn('tnNewEmail').value,current_password:$tn('tnVerifyPassword').value});
    $tn('tnVerifyPassword').value='';premiumSuccess(result.message);
  }catch(error){premiumError(error);}
}

function destroyPremiumChart(name){
  if(premiumCharts[name]){premiumCharts[name].destroy();premiumCharts[name]=null;}
}
function moneyChartOptions(){
  return {responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{usePointStyle:true}}},
    scales:{x:{grid:{display:false}},y:{beginAtZero:true,grid:{color:'#e7eaf2'}}}};
}
async function loadPremiumIncomeExpenseChart(kind){
  const data=await premiumGet('/api/finance/analytics/');
  const canvasId=kind+'PageChart';
  destroyPremiumChart(canvasId);
  premiumCharts[canvasId]=new Chart($tn(canvasId),{
    type:'line',
    data:{labels:data.monthly.map(x=>x.month),datasets:[{
      label:kind==='income'?'Income (NPR)':'Expenses (NPR)',
      data:data.monthly.map(x=>Number(x[kind])),
      borderColor:kind==='income'?'#18aa78':'#ed5968',
      backgroundColor:kind==='income'?'rgba(24,170,120,.12)':'rgba(237,89,104,.12)',
      fill:true,tension:.24,pointRadius:3
    }]},
    options:moneyChartOptions()
  });
}

async function loadPremiumAnalytics(){
  const from=$tn('tnReportFrom').value,to=$tn('tnReportTo').value;
  const query=new URLSearchParams();
  if(from)query.set('from',from);if(to)query.set('to',to);
  const data=await premiumGet('/api/finance/analytics/?'+query.toString());
  premiumAnalyticsData=data;
  $tn('tnReportIncome').textContent=premiumMoney(data.income);
  $tn('tnReportExpense').textContent=premiumMoney(data.expense);
  $tn('tnReportBalance').textContent=premiumMoney(data.balance);
  for(const key of ['tnReportBar','tnReportDonut','tnReportLine'])destroyPremiumChart(key);
  const m=data.monthly;
  premiumCharts.tnReportBar=new Chart($tn('tnReportBar'),{
    type:'bar',data:{labels:m.map(x=>x.month),datasets:[
      {label:'Income',data:m.map(x=>x.income),backgroundColor:'#1fab7f',borderRadius:5},
      {label:'Expense',data:m.map(x=>x.expense),backgroundColor:'#6259e7',borderRadius:5}]},
    options:moneyChartOptions()});
  const palette=['#6659e9','#3d9feb','#14b89b','#f7b54e','#f07593','#b794f6'];
  premiumCharts.tnReportDonut=new Chart($tn('tnReportDonut'),{
    type:'doughnut',data:{labels:data.categories.length?data.categories.map(c=>c.name):['No expense data'],
      datasets:[{data:data.categories.length?data.categories.map(c=>c.amount):[1],
        backgroundColor:data.categories.length?palette:['#e6eaf2'],borderWidth:0}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'65%',plugins:{legend:{position:'bottom',labels:{usePointStyle:true}}}}});
  premiumCharts.tnReportLine=new Chart($tn('tnReportLine'),{
    type:'line',data:{labels:m.map(x=>x.month),datasets:[
      {label:'Income',data:m.map(x=>x.income),borderColor:'#16a876',tension:.25},
      {label:'Expense',data:m.map(x=>x.expense),borderColor:'#6659e9',tension:.25}]},
    options:moneyChartOptions()});
  // Only unfiltered data should update the all-time dashboard totals.
  if(!from&&!to){
    $tn('totalBalance').textContent=premiumMoney(data.balance);
    const month=trackNestToday().slice(0,7);
    const row=m.find(x=>x.month===month)||{income:0,expense:0};
    $tn('totalIncomeMonth').textContent=premiumMoney(row.income);
    $tn('totalSpent').textContent=premiumMoney(row.expense);
    $tn('totalSavingsMonth').textContent=premiumMoney(row.income-row.expense);
    updatePremiumOverviewCharts(data);
  }
}
function updatePremiumOverviewCharts(data){
  const months=data.monthly.slice(-6);
  if(tnOverviewChart){
    tnOverviewChart.data.labels=months.map(x=>x.month);
    tnOverviewChart.data.datasets[0].data=months.map(x=>x.income);
    tnOverviewChart.data.datasets[1].data=months.map(x=>x.expense);
    tnOverviewChart.update();
  }
  if(tnCategoryChart){
    const categories=data.current_month_categories || [];
    tnCategoryChart.data.labels=categories.length?categories.map(x=>x.name):['No expenses yet'];
    tnCategoryChart.data.datasets[0].data=categories.length?categories.map(x=>x.amount):[1];
    tnCategoryChart.data.datasets[0].backgroundColor=categories.length?['#6557e9','#38a3f5','#12af90','#f4ab48','#f16c82','#9b7af4','#75b8d9']:['#e6eaf2'];
    tnCategoryChart.update();
  }
}
function downloadPremiumTransactionCSV(){
  const query=new URLSearchParams();
  const from=$tn('txDateFrom').value,to=$tn('txDateTo').value;
  if(from)query.set('from',from);
  if(to)query.set('to',to);
  window.location.href='/api/finance/export.csv?'+query.toString();
}

function downloadPremiumReport(format){
  const query=new URLSearchParams();
  if($tn('tnReportFrom').value)query.set('from',$tn('tnReportFrom').value);
  if($tn('tnReportTo').value)query.set('to',$tn('tnReportTo').value);
  const url='/api/finance/export.'+format+'?'+query.toString();
  window.location.href=url;
}


/* Fall back to the same authenticated transaction state that powers summary cards.
   This prevents an empty overview if the separate analytics request is unavailable. */
function buildSpendingOverviewFromTransactions(records) {
  const today = new Date();
  const todayKey = trackNestToday();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const prev = new Date(today.getFullYear(), today.getMonth()-1, 1);
  const fmt = d => d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const monthKey = d => fmt(d).slice(0,7);
  const firstKey=monthKey(first), prevKey=monthKey(prev);
  const amountsByDate=new Map(), amountsByMonth=new Map(), byCategory=new Map();
  let currentCount=0, previousCount=0;
  for(const transaction of records){
    if(transaction.type!=='expense') continue;
    const day=String(transaction.date || '').slice(0,10);
    const value=Number(transaction.amount);
    if(day.length!==10 || day>todayKey || !Number.isFinite(value) || value<=0) continue;
    amountsByDate.set(day,(amountsByDate.get(day)||0)+value);
    const month=day.slice(0,7);
    amountsByMonth.set(month,(amountsByMonth.get(month)||0)+value);
    if(month===firstKey){
      currentCount++;
      const category=transaction.category || 'Other';
      byCategory.set(category,(byCategory.get(category)||0)+value);
    } else if(month===prevKey){previousCount++;}
  }
  const daySeries = count => Array.from({length:count},(_,i)=>{
    const date=new Date(today.getFullYear(),today.getMonth(),today.getDate()-(count-1-i));
    const day=fmt(date);
    return {date:day,label:date.toLocaleDateString('en-US',{day:'2-digit',month:'short'}),amount:amountsByDate.get(day)||0};
  });
  const sixMonths=Array.from({length:6},(_,i)=>{
    const date=new Date(today.getFullYear(),today.getMonth()-(5-i),1);
    return {month:monthKey(date),label:date.toLocaleDateString('en-US',{month:'short',year:'numeric'}),
      amount:amountsByMonth.get(monthKey(date))||0};
  });
  const categories=[...byCategory].map(([name,amount])=>({name,amount})).sort((a,b)=>b.amount-a.amount);
  const currentTotal=amountsByMonth.get(firstKey)||0, prevTotal=amountsByMonth.get(prevKey)||0;
  const budget = (typeof userBudgetLimit==='number' && budgetConfigured && userBudgetLimit>0)
    ? userBudgetLimit : null;
  return {periods:{'7d':daySeries(7),'30d':daySeries(30),'6m':sixMonths},
    current_total:currentTotal,previous_total:prevTotal,
    monthly_transactions:currentCount,previous_transactions:previousCount,
    daily_average:currentTotal/today.getDate(),
    budget_used_percent:budget?100*currentTotal/budget:null,
    top_category:categories[0]||null,categories};
}

/* Clear, user-data-backed Spending Overview with daily and monthly exploration. */
let tnSpendingData = null;
let tnSpendingPeriod = '7d';
function tnFormatSpending(value) { return premiumMoney(value); }
function tnSpendingCount(value) {
  const n=Number(value)||0;
  return n+' transaction'+(n===1?'':'s');
}
async function loadSpendingOverview() {
  // Show an immediate picture from already authenticated finance state, and
  // reconcile it with the full analytics endpoint when available.
  const local=Array.isArray(transactions)
    ? buildSpendingOverviewFromTransactions(transactions) : null;
  if(local) renderSpendingOverview(local, false);
  try {
    const result=await premiumGet('/api/finance/spending-overview/');
    // Protect against unexpectedly empty API responses when the finance state
    // already confirms current-month expenses. Keep a visible explanation.
    if(local && local.monthly_transactions>0 && result.monthly_transactions===0) {
      $tn('tnSpendingInsightNote').textContent=
        'Displaying your saved expense records. The full analytics totals did not match your transactions.';
      console.warn('Spending overview mismatch with finance state', result);
      return;
    }
    renderSpendingOverview(result, true);
  } catch(error) {
    const note=$tn('tnSpendingInsightNote');
    if(note) note.textContent='Showing spending from your saved transactions. The full overview could not refresh: '+
      (error.message || 'Please refresh the page.');
    console.error('TrackNest Spending Overview API failed',error);
  }
}
function renderSpendingOverview(result, fromServer) {
  tnSpendingData=result;
  $tn('tnInsightsMonthTotal').textContent=tnFormatSpending(result.current_total);
  $tn('tnInsightsPreviousTotal').textContent=tnFormatSpending(result.previous_total);
  $tn('tnInsightsDailyAverage').textContent=tnFormatSpending(result.daily_average);
  $tn('tnInsightsMonthCount').textContent=tnSpendingCount(result.monthly_transactions)+' this month';
  $tn('tnInsightsTopCategory').textContent=result.top_category ? result.top_category.name : 'No expenses yet';
  $tn('tnInsightsTopCategoryAmount').textContent=result.top_category
    ? tnFormatSpending(result.top_category.amount)+' this month'
    : 'Your top category will appear here';
  const previous=Number(result.previous_total);
  const current=Number(result.current_total);
  $tn('tnInsightsComparison').textContent = previous > 0
    ? (current > previous ? '↑ ' : current < previous ? '↓ ' : '→ ') +
      Math.abs((current-previous)/previous*100).toFixed(1)+'% vs last month'
    : 'No previous-month spending';
  const ratio=result.budget_used_percent;
  const budgetNote=ratio === null ? 'Set a budget to see your spending progress.' :
    'You have used '+Number(ratio).toFixed(1)+'% of this month’s budget.';
  const topNote=result.top_category
    ? 'Your largest category this month is '+result.top_category.name+
      ' ('+tnFormatSpending(result.top_category.amount)+'). '
    : 'No expenses recorded this month. ';
  $tn('tnSpendingInsightNote').textContent=topNote+budgetNote;
  renderSpendingCategories(result.categories || []);
  changeSpendingPeriod(tnSpendingPeriod);
}
function changeSpendingPeriod(period) {
  if(!['7d','30d','6m'].includes(period)) return;
  tnSpendingPeriod=period;
  for(const button of document.querySelectorAll('[data-tn-spending-period]')){
    const selected=button.dataset.tnSpendingPeriod===period;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-pressed',String(selected));
  }
  if(!tnSpendingData) return;
  const items=tnSpendingData.periods[period]||[];
  const total=items.reduce((acc,p)=>acc+Number(p.amount),0);
  const labels=items.map(p=>p.label);
  const values=items.map(p=>Number(p.amount));
  const isMonthly=period==='6m';
  $tn('tnSpendingTrendHeading').textContent=isMonthly?'Expenses by month':'Daily spending';
  $tn('tnSpendingTrendTotal').textContent=tnFormatSpending(total)+' in selected period';
  $tn('tnSpendingTrendDescription').textContent=total>0
    ? (isMonthly ? 'Each bar is the total recorded for that month.' : 'Hover over a bar to see the amount spent that day.')+
      ' Amounts reflect saved expenses, not forecasts.'
    : 'No expenses recorded in this period yet. Select a different range or add an expense.';
  const fallback=$tn('tnSpendingTrendFallback');
  if(typeof Chart==='undefined') {
    // Do not show a blank chart if the external charting library is blocked/offline.
    if(fallback) {
      fallback.hidden=false;
      fallback.replaceChildren();
      const max=Math.max(1,...values);
      for(let i=0;i<items.length;i++) {
        const row=document.createElement('div');row.className='tn-fallback-spending-row';
        const name=document.createElement('span');name.textContent=labels[i];
        const bar=document.createElement('div');bar.className='tn-fallback-spending-track';
        const fill=document.createElement('i');fill.style.width=(100*values[i]/max)+'%';
        bar.appendChild(fill);
        const amount=document.createElement('strong');amount.textContent=tnFormatSpending(values[i]);
        row.append(name,bar,amount);fallback.appendChild(row);
      }
    }
    $tn('tnSpendingTrendChart').hidden=true;
    return;
  }
  if(fallback){fallback.hidden=true;fallback.replaceChildren();}
  $tn('tnSpendingTrendChart').hidden=false;
  destroyPremiumChart('tnSpendingTrendChart');
  premiumCharts.tnSpendingTrendChart=new Chart($tn('tnSpendingTrendChart'),{
    type:'bar',
    data:{labels,datasets:[{
      label:'Expenses (NPR)',data:values,
      backgroundColor:values.map(v=>v>0?'rgba(110,111,255,.82)':'rgba(110,111,255,.18)'),
      hoverBackgroundColor:'#8f85ff',
      borderRadius:7, maxBarThickness:isMonthly?55:24
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},
        tooltip:{callbacks:{label:ctx=>'Spent: '+tnFormatSpending(ctx.parsed.y)}}},
      scales:{
        x:{grid:{display:false},ticks:{color:'#aabbd3',maxTicksLimit:isMonthly?6:period==='7d'?7:10,maxRotation:0}},
        y:{beginAtZero:true,grid:{color:'rgba(180,199,228,.13)'},
          ticks:{color:'#aabbd3',callback:v=>Number(v).toLocaleString('en-US')}}
      }
    }
  });
}
function renderSpendingCategories(categories) {
  const list=$tn('tnSpendingCategoryList');
  list.replaceChildren();
  const palette=['#7b70ff','#38bdf8','#26ce9c','#ffbe5c','#f5809e','#aa9dfa','#72ced8'];
  const total=categories.reduce((sum,c)=>sum+Number(c.amount),0);
  $tn('tnSpendingCategoryCenter').textContent=total>0?tnFormatSpending(total):'No expenses';
  if(typeof Chart!=='undefined') {
  $tn('tnSpendingCategoryChart').hidden=false;
  destroyPremiumChart('tnSpendingCategoryChart');
  premiumCharts.tnSpendingCategoryChart=new Chart($tn('tnSpendingCategoryChart'),{
    type:'doughnut',data:{
      labels:categories.length?categories.map(c=>c.name):['No expense data'],
      datasets:[{data:categories.length?categories.map(c=>Number(c.amount)):[1],
        backgroundColor:categories.length?categories.map((_,i)=>palette[i%palette.length]):['#38465b'],
        borderWidth:0,hoverOffset:6}]
    },options:{responsive:true,maintainAspectRatio:false,cutout:'74%',
       plugins:{legend:{display:false},
         tooltip:{enabled:categories.length>0,callbacks:{label:ctx=>ctx.label+': '+tnFormatSpending(ctx.parsed)}}}}
  });
  } else {
    $tn('tnSpendingCategoryChart').hidden=true;
    $tn('tnSpendingCategoryCenter').textContent=total>0?'Category totals shown below':'No expenses';
  }
  if(!categories.length){
    const p=document.createElement('p');p.textContent='No spending categories yet.';list.appendChild(p);return;
  }
  const fragment=document.createDocumentFragment();
  categories.slice(0,6).forEach((c,i)=>{
    const row=document.createElement('div');row.className='tn-spending-cat-row';
    const name=document.createElement('span');name.className='tn-spending-cat-label';
    const dot=document.createElement('i');dot.style.backgroundColor=palette[i%palette.length];dot.setAttribute('aria-hidden','true');
    name.append(dot,document.createTextNode(c.name));
    const details=document.createElement('span');details.className='tn-spending-cat-value';
    details.textContent=(100*Number(c.amount)/total).toFixed(0)+'% · '+tnFormatSpending(c.amount);
    row.append(name,details);fragment.appendChild(row);
  });
  list.appendChild(fragment);
}


/* Income Overview reuses the expense insight layout with income-only data. */
/* Fall back to the same authenticated transaction state that powers summary cards.
   This prevents an empty overview if the separate analytics request is unavailable. */
function buildIncomeOverviewFromTransactions(records) {
  const today = new Date();
  const todayKey = trackNestToday();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const prev = new Date(today.getFullYear(), today.getMonth()-1, 1);
  const fmt = d => d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
  const monthKey = d => fmt(d).slice(0,7);
  const firstKey=monthKey(first), prevKey=monthKey(prev);
  const amountsByDate=new Map(), amountsByMonth=new Map(), byCategory=new Map();
  let currentCount=0, previousCount=0;
  for(const transaction of records){
    if(transaction.type!=='income') continue;
    const day=String(transaction.date || '').slice(0,10);
    const value=Number(transaction.amount);
    if(day.length!==10 || day>todayKey || !Number.isFinite(value) || value<=0) continue;
    amountsByDate.set(day,(amountsByDate.get(day)||0)+value);
    const month=day.slice(0,7);
    amountsByMonth.set(month,(amountsByMonth.get(month)||0)+value);
    if(month===firstKey){
      currentCount++;
      const category=transaction.category || 'Other';
      byCategory.set(category,(byCategory.get(category)||0)+value);
    } else if(month===prevKey){previousCount++;}
  }
  const daySeries = count => Array.from({length:count},(_,i)=>{
    const date=new Date(today.getFullYear(),today.getMonth(),today.getDate()-(count-1-i));
    const day=fmt(date);
    return {date:day,label:date.toLocaleDateString('en-US',{day:'2-digit',month:'short'}),amount:amountsByDate.get(day)||0};
  });
  const sixMonths=Array.from({length:6},(_,i)=>{
    const date=new Date(today.getFullYear(),today.getMonth()-(5-i),1);
    return {month:monthKey(date),label:date.toLocaleDateString('en-US',{month:'short',year:'numeric'}),
      amount:amountsByMonth.get(monthKey(date))||0};
  });
  const categories=[...byCategory].map(([name,amount])=>({name,amount})).sort((a,b)=>b.amount-a.amount);
  const currentTotal=amountsByMonth.get(firstKey)||0, prevTotal=amountsByMonth.get(prevKey)||0;
  return {periods:{'7d':daySeries(7),'30d':daySeries(30),'6m':sixMonths},
    current_total:currentTotal,previous_total:prevTotal,
    monthly_transactions:currentCount,previous_transactions:previousCount,
    daily_average:currentTotal/today.getDate(),
    top_category:categories[0]||null,categories};
}

/* Clear, user-data-backed Income Overview with daily and monthly exploration. */
let tnIncomeData = null;
let tnIncomePeriod = '7d';
function tnFormatIncome(value) { return premiumMoney(value); }
function tnIncomeCount(value) {
  const n=Number(value)||0;
  return n+' transaction'+(n===1?'':'s');
}
async function loadIncomeOverview() {
  // Show an immediate picture from already authenticated finance state, and
  // reconcile it with the full analytics endpoint when available.
  const local=Array.isArray(transactions)
    ? buildIncomeOverviewFromTransactions(transactions) : null;
  if(local) renderIncomeOverview(local, false);
  try {
    const result=await premiumGet('/api/finance/income-overview/');
    // Protect against unexpectedly empty API responses when the finance state
    // already confirms current-month expenses. Keep a visible explanation.
    if(local && local.monthly_transactions>0 && result.monthly_transactions===0) {
      $tn('tnIncomeInsightNote').textContent=
        'Displaying your saved income records. The full analytics totals did not match your transactions.';
      console.warn('Income overview mismatch with finance state', result);
      return;
    }
    renderIncomeOverview(result, true);
  } catch(error) {
    const note=$tn('tnIncomeInsightNote');
    if(note) note.textContent='Showing income from your saved transactions. The full overview could not refresh: '+
      (error.message || 'Please refresh the page.');
    console.error('TrackNest Income Overview API failed',error);
  }
}
function renderIncomeOverview(result, fromServer) {
  tnIncomeData=result;
  $tn('tnIncomeInsightsMonthTotal').textContent=tnFormatIncome(result.current_total);
  $tn('tnIncomeInsightsPreviousTotal').textContent=tnFormatIncome(result.previous_total);
  $tn('tnIncomeInsightsDailyAverage').textContent=tnFormatIncome(result.daily_average);
  $tn('tnIncomeInsightsMonthCount').textContent=tnIncomeCount(result.monthly_transactions)+' this month';
  $tn('tnIncomeInsightsTopCategory').textContent=result.top_category ? result.top_category.name : 'No income yet';
  $tn('tnIncomeInsightsTopCategoryAmount').textContent=result.top_category
    ? tnFormatIncome(result.top_category.amount)+' this month'
    : 'Your top category will appear here';
  const previous=Number(result.previous_total);
  const current=Number(result.current_total);
  $tn('tnIncomeInsightsComparison').textContent = previous > 0
    ? (current > previous ? '↑ ' : current < previous ? '↓ ' : '→ ') +
      Math.abs((current-previous)/previous*100).toFixed(1)+'% vs last month'
    : 'No income recorded last month';
  const budgetNote='This overview includes only saved income records.';
  const topNote=result.top_category
    ? 'Your largest income source this month is '+result.top_category.name+
      ' ('+tnFormatIncome(result.top_category.amount)+'). '
    : 'No income recorded this month. ';
  $tn('tnIncomeInsightNote').textContent=topNote+budgetNote;
  renderIncomeCategories(result.categories || []);
  changeIncomePeriod(tnIncomePeriod);
}
function changeIncomePeriod(period) {
  if(!['7d','30d','6m'].includes(period)) return;
  tnIncomePeriod=period;
  for(const button of document.querySelectorAll('[data-tn-income-period]')){
    const selected=button.dataset.tnIncomePeriod===period;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-pressed',String(selected));
  }
  if(!tnIncomeData) return;
  const items=tnIncomeData.periods[period]||[];
  const total=items.reduce((acc,p)=>acc+Number(p.amount),0);
  const labels=items.map(p=>p.label);
  const values=items.map(p=>Number(p.amount));
  const isMonthly=period==='6m';
  $tn('tnIncomeTrendHeading').textContent=isMonthly?'Income by month':'Daily income';
  $tn('tnIncomeTrendTotal').textContent=tnFormatIncome(total)+' in selected period';
  $tn('tnIncomeTrendDescription').textContent=total>0
    ? (isMonthly ? 'Each bar is the total recorded for that month.' : 'Hover over a bar to see the amount spent that day.')+
      ' Amounts reflect saved income, not forecasts.'
    : 'No income recorded in this period yet. Select a different range or add an expense.';
  const fallback=$tn('tnIncomeTrendFallback');
  if(typeof Chart==='undefined') {
    // Do not show a blank chart if the external charting library is blocked/offline.
    if(fallback) {
      fallback.hidden=false;
      fallback.replaceChildren();
      const max=Math.max(1,...values);
      for(let i=0;i<items.length;i++) {
        const row=document.createElement('div');row.className='tn-fallback-spending-row';
        const name=document.createElement('span');name.textContent=labels[i];
        const bar=document.createElement('div');bar.className='tn-fallback-spending-track';
        const fill=document.createElement('i');fill.style.width=(100*values[i]/max)+'%';
        bar.appendChild(fill);
        const amount=document.createElement('strong');amount.textContent=tnFormatIncome(values[i]);
        row.append(name,bar,amount);fallback.appendChild(row);
      }
    }
    $tn('tnIncomeTrendChart').hidden=true;
    return;
  }
  if(fallback){fallback.hidden=true;fallback.replaceChildren();}
  $tn('tnIncomeTrendChart').hidden=false;
  destroyPremiumChart('tnIncomeTrendChart');
  premiumCharts.tnIncomeTrendChart=new Chart($tn('tnIncomeTrendChart'),{
    type:'bar',
    data:{labels,datasets:[{
      label:'Income (NPR)',data:values,
      backgroundColor:values.map(v=>v>0?'rgba(32,201,147,.82)':'rgba(32,201,147,.18)'),
      hoverBackgroundColor:'#25c994',
      borderRadius:7, maxBarThickness:isMonthly?55:24
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},
        tooltip:{callbacks:{label:ctx=>'Received: '+tnFormatIncome(ctx.parsed.y)}}},
      scales:{
        x:{grid:{display:false},ticks:{color:'#aabbd3',maxTicksLimit:isMonthly?6:period==='7d'?7:10,maxRotation:0}},
        y:{beginAtZero:true,grid:{color:'rgba(180,199,228,.13)'},
          ticks:{color:'#aabbd3',callback:v=>Number(v).toLocaleString('en-US')}}
      }
    }
  });
}
function renderIncomeCategories(categories) {
  const list=$tn('tnIncomeCategoryList');
  list.replaceChildren();
  const palette=['#1cc994','#38bdf8','#7b70ff','#ffbe5c','#f5809e','#aa9dfa','#72ced8'];
  const total=categories.reduce((sum,c)=>sum+Number(c.amount),0);
  $tn('tnIncomeCategoryCenter').textContent=total>0?tnFormatIncome(total):'No income';
  if(typeof Chart!=='undefined') {
  $tn('tnIncomeCategoryChart').hidden=false;
  destroyPremiumChart('tnIncomeCategoryChart');
  premiumCharts.tnIncomeCategoryChart=new Chart($tn('tnIncomeCategoryChart'),{
    type:'doughnut',data:{
      labels:categories.length?categories.map(c=>c.name):['No expense data'],
      datasets:[{data:categories.length?categories.map(c=>Number(c.amount)):[1],
        backgroundColor:categories.length?categories.map((_,i)=>palette[i%palette.length]):['#38465b'],
        borderWidth:0,hoverOffset:6}]
    },options:{responsive:true,maintainAspectRatio:false,cutout:'74%',
       plugins:{legend:{display:false},
         tooltip:{enabled:categories.length>0,callbacks:{label:ctx=>ctx.label+': '+tnFormatIncome(ctx.parsed)}}}}
  });
  } else {
    $tn('tnIncomeCategoryChart').hidden=true;
    $tn('tnIncomeCategoryCenter').textContent=total>0?'Category totals shown below':'No income';
  }
  if(!categories.length){
    const p=document.createElement('p');p.textContent='No income sources yet.';list.appendChild(p);return;
  }
  const fragment=document.createDocumentFragment();
  categories.slice(0,6).forEach((c,i)=>{
    const row=document.createElement('div');row.className='tn-spending-cat-row';
    const name=document.createElement('span');name.className='tn-spending-cat-label';
    const dot=document.createElement('i');dot.style.backgroundColor=palette[i%palette.length];dot.setAttribute('aria-hidden','true');
    name.append(dot,document.createTextNode(c.name));
    const details=document.createElement('span');details.className='tn-spending-cat-value';
    details.textContent=(100*Number(c.amount)/total).toFixed(0)+'% · '+tnFormatIncome(c.amount);
    row.append(name,details);fragment.appendChild(row);
  });
  list.appendChild(fragment);
}


/* Real historical expense forecasting — no fixed multiplier or fabricated series. */
async function loadExpenseForecast() {
  const data=await premiumGet('/api/finance/forecast/');
  const format=premiumMoney;
  $tn('tnForecastCurrentActual').textContent=format(data.current_month_spent);
  $tn('tnForecastCurrentLabel').textContent=data.current_month_label;
  $tn('tnForecastNextLabel').textContent=data.next_month_label;
  const ready=data.status==='ready';
  $tn('tnForecastCurrentPrediction').textContent=ready?format(data.forecast_current):'Not enough data';
  $tn('tnForecastNextPrediction').textContent=ready?format(data.forecast_next):'Not enough data';
  $tn('tnForecastMAE').textContent=data.mae===null?'Not available':format(data.mae);
  $tn('tnForecastModelState').textContent=ready?'Linear Regression ready':'More history needed';
  $tn('tnForecastModelState').classList.toggle('is-ready',ready);
  $tn('tnForecastTrainingSummary').textContent=data.training_months+' completed month'+
    (data.training_months===1?'':'s')+' · '+data.active_training_months+' with spending';
  const slope=Number(data.slope_per_month);
  $tn('tnForecastTrend').textContent=ready
    ? (slope>0?'↑ Increasing':slope<0?'↓ Decreasing':'→ Stable')+' '+format(Math.abs(slope))+'/month'
    : 'Not enough history';
  $tn('tnForecastSlopeNote').textContent=ready
    ? 'The fitted line changes by this amount each month.'
    : 'At least three completed months with spending are required.';
  $tn('tnForecastValidation').textContent=data.mae===null?'Not evaluated yet':
    'Average error '+format(data.mae);
  $tn('tnForecastChartNote').textContent=ready
    ? 'Blue bars are actual saved monthly expenses. Yellow dotted values estimate this month and next month; they are not guaranteed future spending.'
    : 'Blue bars are real completed-month spending. No yellow prediction is shown until at least three completed months have spending.';

  $tn('tnForecastExplanation').textContent=ready
    ? 'Based on '+data.training_months+' completed months ('+data.active_training_months+
      ' months with spending). '+(data.backtest_count
      ? 'Historical mean absolute error: '+format(data.mae)+' over '+data.backtest_count+' backtests. '
      : 'Not enough historical months for backtest validation. ')+data.method_note
    : data.reason+' Your current recorded spending is shown, but TrackNest will not invent predictions.';
  if(typeof forecastChart==='undefined') return;
  const completed=data.history || [];
  const labels=completed.map(row=>row.label).concat([data.current_month_label,data.next_month_label]);
  const actual=completed.map(row=>Number(row.amount)).concat([Number(data.current_month_spent),null]);
  const predicted=Array(labels.length).fill(null);
  if(ready){
    // Attach the forecast to the last actual month to make the trend easy to follow.
    if(completed.length) predicted[completed.length-1]=Number(completed[completed.length-1].amount);
    predicted[completed.length]=Number(data.forecast_current);
    predicted[completed.length+1]=Number(data.forecast_next);
  }
  forecastChart.data.labels=labels;
  forecastChart.data.datasets[0].data=actual;
  forecastChart.data.datasets[1].data=predicted;
  forecastChart.update();
}

/* A live explanation of TrackNest's exact monthly budget thresholds. */
function updateBudgetProtectionGuide() {
  const section=$tn('tnBudgetProtectionStatus');
  if(!section) return;
  const limit=Number(userBudgetLimit);
  const spent=Number(currentMonthlySpent)||0;
  const configured=Boolean(budgetConfigured && limit>0 && Number.isFinite(limit));
  const percent=configured?(spent/limit*100):0;
  const stage=!configured?'unset':percent>=100?'limit':percent>=90?'critical':percent>=80?'warning':'normal';
  const labels={unset:'Set your budget first',normal:'Normal · below 80%',
    warning:'Warning · 80% reached',critical:'Critical · 90% reached',limit:'Limit reached · 100%'};
  section.textContent=labels[stage];
  section.dataset.stage=stage;
  $tn('tnBudgetProtectionUsage').textContent=configured?percent.toFixed(1)+'% used':'Budget not configured';
  $tn('tnBudgetProtectionRemaining').textContent=configured
    ? premiumMoney(Math.max(0,limit-spent))+' remaining of '+premiumMoney(limit)
    : 'Choose a monthly limit to activate protection.';
  $tn('tnBudgetProtectionFill').style.width=(configured?Math.max(0,Math.min(100,percent)):0)+'%';
  $tn('tnBudgetProtectionBar').setAttribute('aria-valuenow',String(Math.max(0,Math.min(100,Math.round(percent)))));
  $tn('tnBudgetProtectionBar').dataset.stage=stage;
  for(const item of document.querySelectorAll('[data-budget-threshold]')){
    item.classList.toggle('is-current',item.dataset.budgetThreshold===stage);
  }
}
