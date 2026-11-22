/* TrackNest premium module interactions. Uses existing session + CSRF helpers. */
let premiumCategories = [];
let premiumBudgets = [];
let premiumGoals = [];
let premiumNotifications = [];
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
    await Promise.all([loadPremiumCategories(),loadPremiumNotifications(),loadPremiumAnalytics(),loadPremiumSettings()]);
    await Promise.all([loadPremiumBudgets(),loadPremiumGoals()]);
    renderPremiumCategorySelectors();
  } catch(error){console.error('Premium module loading failed', error);premiumError(error);}
}
async function loadPremiumSection(section){
  try {
    if(section==='categories') await loadPremiumCategories();
    else if(section==='budget') {await loadPremiumCategories();await loadPremiumBudgets();}
    else if(section==='goals') await loadPremiumGoals();
    else if(section==='notifications') await loadPremiumNotifications();
    else if(section==='reports') await loadPremiumAnalytics();
    else if(section==='settings') await loadPremiumSettings();
    else if(section==='profile') populatePremiumProfile();
  } catch(error) {premiumError(error);}
}
function renderPremiumCategorySelectors(){
  const select=$tn('tnBudgetCategory'); const keep=select.value;
  select.innerHTML='<option value="">Select category</option>'+premiumCategories.filter(c=>c.type==='expense')
    .map(c=>'<option value="'+c.id+'">'+escapeHtml(c.name)+'</option>').join('');
  if(keep)select.value=keep;
  const filter=$tn('tnTransactionCategoryFilter'), filterValue=filter.value;
  const names=[...new Set([...transactions.map(t=>t.category),...premiumCategories.map(c=>c.name)])].sort();
  filter.innerHTML='<option value="">All categories</option>'+names.map(x=>'<option>'+escapeHtml(x)+'</option>').join('');
  filter.value=filterValue;
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
  }).join(''):'<p class="tn-premium-empty">No category budgets yet. Create an expense category first, then add a budget.</p>';
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
      id:id?Number(id):undefined,category_id:Number($tn('tnBudgetCategory').value),
      limit:$tn('tnBudgetAmount').value,month:trackNestToday().slice(0,7)+'-01'});
    resetPremiumCategoryBudget();await loadPremiumBudgets();premiumSuccess('Category budget saved.');
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
    const month=trackNestToday().slice(0,7);
    // Monthly category breakdown is already built from the saved transaction list;
    // refresh it from server-wide totals only when explicitly filtered by month.
    tnCategoryChart.update();
  }
}
function downloadPremiumReport(format){
  const query=new URLSearchParams();
  if($tn('tnReportFrom').value)query.set('from',$tn('tnReportFrom').value);
  if($tn('tnReportTo').value)query.set('to',$tn('tnReportTo').value);
  const url='/api/finance/export.'+format+'?'+query.toString();
  window.location.href=url;
}
