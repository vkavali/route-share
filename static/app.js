import { busyMark, beginBusy } from './seatpal-busy.js';
import { messages, placeLabels } from './i18n.js';
import { accessCopy } from './access-copy.js';
import { pickLocation, mountJourneyMap } from './map-picker.js';
import { mountLiveLocation } from './live-location.js';
import { appIcon } from './icons.js';
import { renderLogin, renderHome, renderSearchForm, renderDriveForm, renderBecomeDriver } from './reference-shell.js';
import { makeTripViews } from './reference-trip.js';
import { makeJourneyViews } from './reference-journeys.js';
import { makeCommunity } from './community.js';
import { makeAccountFlows } from './account-flows.js';
import { makeIdentityFlows } from './identity-flows.js';
import { makePhoneAuth } from './phone-auth.js';
import { mountTripSharing, clearTripSharingState } from './trip-sharing.js';
import { seedBlankJourneyTimes, seedJourneyTimes, validateJourneyTime, bindPickupWindow } from './journey-time.js';
import { captureLandingIntent, consumeLandingIntent } from './landing-intent.js';
import { createFestivalGreeting, startFestivalGreetingUpdates } from './festival-greetings.js';
import { createSessionCoordinator } from './session-coordination.js';
const app = document.querySelector('#app');
captureLandingIntent();
const queryLang=new URLSearchParams(location.search).get('lang');
const storedLang=localStorage.getItem('route-lang');
const state = { boot:null, user:null, csrf:'', lang:['en','te','hi'].includes(queryLang)?queryLang:(['en','te','hi'].includes(storedLang)?storedLang:'en'), data:{trips:[],bookings:[],requests:[],ratings:[]}, preview:null, results:null, resultsMode:'best', fareReviewId:null, busy:false, error:'', notice:'', form:null, formDrafts:{}, routePoints:{origin:null,destination:null}, passwordVisible:false, menuOpen:false, liveCleanup:null, liveBookingId:null, liveElement:null, journeyMapCleanup:null, blockConfirm:null, reportKeys:{}, adminResolutionDrafts:{}, sessionVersion:0, sessionSyncing:false, sessionSyncFailed:false, logoutPending:false, logoutRetrying:false, logoutFailed:false, logoutChangedAccount:false, logoutAttempt:null };
const hostedBeta = () => state.boot?.mode==='hosted_beta';
const t = key => {const k=hostedBeta()?({beta:'hostedBeta',privateBetaNotice:'hostedBetaNotice',developmentAccountsFootnote:'hostedAccountsFootnote',safety:'hostedAccountsFootnote'}[key]||key):key;return messages[state.lang]?.[k] ?? accessCopy[state.lang]?.[key] ?? (state.lang==='te' ? 'వివరాలు లేవు' : messages.en[k] ?? accessCopy.en[key] ?? k)};
const safetyNotice=()=>state.boot?.flags?.public_registration_enabled===true?t('phoneProofOnly'):t('safety');
const locale = () => state.lang==='te'?'te-IN':state.lang==='hi'?'hi-IN':'en-IN';
document.documentElement.lang=state.lang;
function changeLanguage(lang){if(!['en','te','hi'].includes(lang))return;state.lang=lang;localStorage.setItem('route-lang',lang);const u=new URL(location.href);u.searchParams.set('lang',lang);history.replaceState(null,'',u.pathname+u.search+u.hash);document.documentElement.lang=lang;document.title=t('documentTitle');}
const placeNames=placeLabels;
const esc = x => String(x ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labelOf = p => {if(!p?.label)return `${p?.lat ?? ''}, ${p?.lon ?? ''}`;const known=placeNames[state.lang];return known&&Object.prototype.hasOwnProperty.call(known,p.label)?known[p.label]:p.label};
const fmtTime = v => v ? new Intl.DateTimeFormat(locale(),{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Kolkata'}).format(new Date(v)) : t('unknown');
const inr = v => v == null ? t('unknown') : new Intl.NumberFormat(locale(),{style:'currency',currency:'INR',maximumFractionDigits:0}).format(v);
const inrPrecise = v => v == null ? t('unknown') : new Intl.NumberFormat(locale(),{style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2}).format(v);
const hasRequestableQuote = quote => quote?.currency==='INR' && Number.isInteger(quote.amount_paise) && quote.amount_paise>=0 && ((quote.version===2&&quote.basis==='passenger_route_per_seat')||(quote.version===1&&quote.basis==='flat_per_seat'));
const dur = s => s == null ? t('unknown') : `${new Intl.NumberFormat(locale(),{maximumFractionDigits:0}).format(Math.round(s/60))} ${t('mins')}`;
const minText = n => n == null ? t('unknown') : `${n>=0?'+':''}${new Intl.NumberFormat(locale(),{maximumFractionDigits:2}).format(Number(n))} ${t('mins')}`;
const escAttr = esc;
const community = makeCommunity({state,t,icon,esc,escAttr,api,refresh:refreshState,render,navigate:nav});
const accountFlows=makeAccountFlows({state,t,esc,icon,api,render,refresh:refreshState,errorMessage,expire:expireSession,labelOf,onDeleted:accountDeleted});
const identityFlows=makeIdentityFlows({state,api,render,refresh:refreshState,expire:expireSession});
const phoneAuth=makePhoneAuth({state,t,esc,api,render,onAuthenticated:phoneAuthenticated,onProfileSaved:phoneProfileSaved});
const sessionCoordinator=createSessionCoordinator({onChange:()=>void revalidateSession({remoteChange:true})});

const backendErrors = new Map([
 ['Sign in to your invited development account.','loginRequired'],['Invalid account or password','invalidCredentials'],['Account and password are required','missingCredentials'],['Invalid CSRF token','csrfError'],['Send a JSON object.','requestInvalid'],['Unknown action.','requestInvalid'],['This record was not found. Refresh and try again.','notFound'],['Choose a point in the Hyderabad east or south pilot corridors.','pilotCorridor'],['Enter a place label and valid latitude and longitude.','pointInvalid'],['Choose a future departure within the next 90 days.','departureWindow'],['Choose a detour of 0, 5, 10 or 15 minutes.','detourAllowed'],['Choose two different points at least 1 km apart.','pointsDifferent'],['Only the preview owner can publish it.','previewOwner'],['The route preview expired. Calculate it again.','previewExpired'],['Choose a future pickup window up to 12 hours, within 90 days.','pickupWindow'],['Choose points at least 1 km apart.','pointsFar'],['This match belongs to another passenger.','otherPassengerMatch'],['This trip is no longer accepting requests.','tripClosed'],['This match has expired. Search again.','matchExpired'],['Only the driver can accept.','driverOnlyAccept'],['This request or trip is no longer available.','bookingUnavailable'],['Another driver has already confirmed this passenger request.','requestConfirmedElsewhere'],['This passenger already holds an overlapping segment on this trip.','overlapExists'],['Only the driver can decline.','driverOnlyDecline'],['This booking belongs to other people.','bookingOtherPeople'],['This booking can no longer be changed. In-progress trips require operator assistance.','bookingNoChange'],['Add a cancellation reason.','cancellationReason'],['Only the driver can change this trip.','driverOnlyChangeTrip'],['This trip status cannot make that transition.','invalidTripTransition'],['Complete every accepted passenger segment before completing the trip.','finishSegmentsFirst'],['Only the passenger or driver can confirm this segment.','participantOnly'],['Start the trip before completing an accepted segment.','startBeforeSegment'],['Only participants may rate this booking.','participantRateOnly'],['Ratings open after the completed journey.','ratingAfterCompletion'],['Operations is restricted to the invited administrator.','adminOnly'],['Choose a safety report category.','chooseReportCategory'],['Describe the concern in 10 to 1000 characters.','invalidReportDetails'],['A valid report request identifier is required.','invalidReportKey'],['This report request was already used. Refresh and try again.','reportKeyReused'],['Only participants can use safety controls for this booking.','safetyNotAllowed'],['Add a resolution in 10 to 1000 characters.','invalidResolution'],['Only an administrator can resolve a safety report.','adminOnlyResolve']
]);
const codedErrorCopy={
  booking_already_exists:{en:'You already have a request for this ride. Open your bookings to review or cancel it.',te:'ఈ రైడ్‌కు మీరు ఇప్పటికే అభ్యర్థన పంపారు. దాన్ని చూడటానికి లేదా రద్దు చేయడానికి మీ బుకింగ్‌లు తెరవండి.',hi:'आपने इस सवारी के लिए पहले ही अनुरोध भेजा है। उसे देखने या रद्द करने के लिए अपनी बुकिंग खोलें।'},
  booking_price_mismatch:{en:'The payment total must match the fare saved with this booking.',te:'చెల్లింపు మొత్తం ఈ బుకింగ్‌తో సేవ్ చేసిన ఛార్జీకి సరిపోవాలి.',hi:'भुगतान की कुल राशि इस बुकिंग में सहेजे गए किराये से मेल खानी चाहिए।'}
};
function errorMessage(error){const raw=String(typeof error==='string'?error:(error?.message||''));const coded=codedErrorCopy[error?.code];if(coded)return coded[state.lang]||coded.en;if(raw==='Sign-in could not be confirmed. Retry.')return sessionCopy().loginFailed;if(backendErrors.has(raw))return t(backendErrors.get(raw));if(raw==='Session expired. Sign in again.')return t('sessionExpired');const range=raw.match(/^(.+?) must be a whole number from (\d+) to (\d+)\.$/);if(range)return t('numberRangeError').replace('{min}',new Intl.NumberFormat(locale()).format(Number(range[2]))).replace('{max}',new Intl.NumberFormat(locale()).format(Number(range[3])));if(raw.startsWith('Availability changed:'))return t('availabilityChanged');if(error?.name==='AbortError')return t('networkTimeout');if(error?.name==='TypeError'||/failed to fetch|networkerror/i.test(raw))return t('networkFailure');if(raw==='Invalid CSRF token')return t('csrfError');if(error?.status===401)return t('loginRequired');if(error?.status===403)return t('forbidden');if(error?.status===404)return t('notFound');if(error?.status===409)return t('stateChanged');if(error?.status===503)return t('providerFailure');if(error?.status===400)return t('requestInvalid');if(error?.status>=500)return t('serverFailure');return t('requestInvalid')}
function sessionCopy(){return ({te:{title:'సైన్ అవుట్ అవుతోంది',failed:'సైన్ అవుట్ నిర్ధారించబడలేదు. మళ్లీ ప్రయత్నించండి.',retry:'మళ్లీ ప్రయత్నించండి',different:'మరొక ఖాతా సక్రియంగా ఉంది. అది మీ ఖాతా అని నిర్ధారించిన తర్వాత మాత్రమే కొనసాగించండి.',continue:'ఈ ఖాతాతో కొనసాగించండి',checking:'మీ సైన్-ఇన్‌ను తనిఖీ చేస్తున్నాం',checkFailed:'మీ ఖాతాను తనిఖీ చేయలేకపోయాం. మీ ప్రైవేట్ సమాచారం దాచబడింది.',loginFailed:'సైన్-ఇన్ నిర్ధారించబడలేదు. మళ్లీ ప్రయత్నించండి.'},hi:{title:'साइन आउट हो रहा है',failed:'साइन आउट की पुष्टि नहीं हो सकी। फिर कोशिश करें।',retry:'फिर कोशिश करें',different:'दूसरा खाता सक्रिय है। पहचानने के बाद ही आगे बढ़ें।',continue:'इस खाते के साथ जारी रखें',checking:'आपके साइन-इन की जाँच हो रही है',checkFailed:'आपके खाते की जाँच नहीं हो सकी। आपकी निजी जानकारी छिपी है।',loginFailed:'साइन-इन की पुष्टि नहीं हो सकी। फिर कोशिश करें।'},en:{title:'Signing out',failed:'Sign-out could not be confirmed. Retry.',retry:'Retry sign-out',different:'Another account is active. Continue only if you recognize it.',continue:'Continue with this account',checking:'Checking your sign-in',checkFailed:'Your account could not be checked. Your private data is hidden.',loginFailed:'Sign-in could not be confirmed. Retry.'}})[state.lang]||{title:'Signing out',failed:'Sign-out could not be confirmed. Retry.',retry:'Retry sign-out',different:'Another account is active. Continue only if you recognize it.',continue:'Continue with this account',checking:'Checking your sign-in',checkFailed:'Your account could not be checked. Your private data is hidden.',loginFailed:'Sign-in could not be confirmed. Retry.'}}
function localizedContribution(value){if(!value)return '';if(/₹\s*2|2\s*(per|each) passenger.?km|passenger.?km/i.test(value))return t('contributionFormula');return value}

async function api(path, method='GET', body, requestOptions={}) {
  const requestSessionVersion=state.sessionVersion;
  const hasExpected=Object.prototype.hasOwnProperty.call(requestOptions,'expectedUserId');
  const expectedUserId=hasExpected?requestOptions.expectedUserId:state.user?.id;
  const csrf=Object.prototype.hasOwnProperty.call(requestOptions,'csrf')?requestOptions.csrf:state.csrf;
  const staleResponse=()=>Object.assign(new Error('The session changed while the request was in progress.'),{status:409,code:'stale_session_response'});
  if(state.logoutPending&&path!=='/api/logout'&&!(path==='/api/bootstrap'&&requestOptions.allowLogout===true))throw staleResponse();
  if(state.sessionSyncing&&!['/api/bootstrap','/api/state'].includes(path))throw staleResponse();
  if(state.logoutPending&&path==='/api/logout'&&requestOptions.allowLogout!==true)throw staleResponse();
  const controller=new AbortController(); const timeout=setTimeout(()=>controller.abort(),20000);
  const opts={signal:controller.signal,method,credentials:'same-origin',headers:{'Accept':'application/json'}};
  if(expectedUserId&&!['/api/bootstrap','/api/login','/api/mobile/login'].includes(path))opts.headers['X-Expected-User-ID']=expectedUserId;
  if(body!==undefined){opts.headers['X-CSRF-Token']=csrf;if(body instanceof FormData)opts.body=body;else{opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body)}}
  try {const res=await fetch(path,opts); const json=await res.json().catch(()=>({error:`HTTP ${res.status}`}));
  if(requestSessionVersion!==state.sessionVersion)throw staleResponse();
  if(!res.ok){const e=new Error(json.error||`HTTP ${res.status}`);e.status=res.status;e.code=json.code;e.path=path;e.retry_after=json.retry_after;if(e.code==='account_changed'&&!state.logoutPending){await revalidateSession({remoteChange:true});e.code='stale_session_response'}throw e} return json;} finally {clearTimeout(timeout)}
}
function isStaff(user=state.user){return user?.access?.is_staff===true||user?.role==='staff'||user?.role==='admin'}
function canDrive(user=state.user){return user?.access?.can_drive===true}
function staffCapabilities(user=state.user){return Array.isArray(user?.access?.staff_capabilities)?user.access.staff_capabilities:[]}
function canReadOps(user=state.user){return isStaff(user)&&staffCapabilities(user).includes('ops.read')}
function canResolveSafety(user=state.user){return isStaff(user)&&staffCapabilities(user).includes('safety.act')}
function landingRoute(user=state.user){return isStaff(user)?'operations':canDrive(user)?'journeys':'home'}
function routeForUser(route,user=state.user){
  if(!user)return route||'login';
  if(user.onboarding_required===true)return 'phone-profile';
  if(!route||route==='login')return landingRoute(user);
  if(isStaff(user))return ['operations','profile','notifications','verification-queue',...(user?.access?.staff_capabilities||[]).includes('verify.review')?['identity-review']:[]].includes(route)?route:'operations';
  if(route==='identity-review')return 'profile';
  if(route==='operations')return landingRoute(user);
  if(route==='drive-form'&&!canDrive(user))return 'verification';
  if(route==='become-driver')return 'verification';
  return route;
}
function currentRoute(){const requested=location.hash.replace(/^#\/?/,'');return routeForUser(requested|| (state.user?'':'login'))}
const festivalGreeting=createFestivalGreeting();
const festivalUpdatesCleanup=startFestivalGreetingUpdates({onChange:()=>{if(state.user&&currentRoute()==='home')render()}});
function ensureFestivalGreetingStyles(){if(document.querySelector('link[data-festival-greeting-styles]'))return;const link=document.createElement('link');link.rel='stylesheet';link.href='/static/festival-greetings.css';link.dataset.festivalGreetingStyles='';document.head.append(link)}
function nav(route){location.hash=`/${routeForUser(route)}`}
function setNotice(s){state.notice=s;state.noticeKey=Object.keys(messages[state.lang]).find(k=>messages[state.lang][k]===s)||({'Signed in.':'signedIn','Search saved.':'searchSaved','Account changed in another tab. Current account data loaded.':'accountChange'}[s]||'saved');state.error=''}
function noticeText(){return state.noticeKey?t(state.noticeKey):t('saved')}
function setError(e){if(e?.code==='stale_session_response')return;state.error=e;state.notice='';state.noticeKey=null}
function icon(name,size=24){const keys={pin:'mapPin',home:'home',route:'path',bookings:'list',inbox:'chatCircleDots',ops:'gear',driver:'steeringWheel',passenger:'user',passenger2:'users',admin:'gear',eye:'eye',eyeSlash:'eyeSlash',search:'magnifyingGlass',swap:'arrowsDownUp',arrowRight:'arrowRight',back:'arrowLeft',lock:'lockKey'};return appIcon(keys[name]||name,{size,className:'ui-icon'})}
function languageSelect(){
  return `<div class="language-control"><div class="language-segments" role="group" aria-label="${t('language')}"><button type="button" lang="en" data-language-choice="en" aria-pressed="${state.lang==='en'}">EN</button><button type="button" lang="te" data-language-choice="te" aria-pressed="${state.lang==='te'}">తెలుగు</button></div><label class="language language-more"><span class="sr-only">${t('language')}</span><select id="language" aria-label="${t('language')}"><option value="en" ${state.lang==='en'?'selected':''}>${t('languageEnglish')}</option><option value="te" ${state.lang==='te'?'selected':''}>${t('languageTelugu')}</option><option value="hi" ${state.lang==='hi'?'selected':''}>${t('languageHindi')}</option></select></label></div>`;
}
function communityNavigation(){const suffix=n=>Number(n)>0?` (${new Intl.NumberFormat(locale()).format(n)})`:'';return [['chats','chatCircleDots',t('communityChats')+suffix(state.data.chat_unread_count)],['notifications','bell',t('communityNotifications')+suffix(state.data.notification_unread_count)],['profile','user',t('communityProfile')]]}
function roleNavigation(){
  if(isStaff())return [...(staffCapabilities().includes('verify.review')?[['verification-queue','lock',t('afQueue')],['identity-review','lockKey',identityFlows.navLabel()]]:[]),['operations','ops',t('operations')],['notifications','bell',t('communityNotifications')+((Number(state.data.notification_unread_count)>0)?` (${new Intl.NumberFormat(locale()).format(state.data.notification_unread_count)})`:'' )],['profile','user',t('communityProfile')]];
  return [['home','home',t('homeNav')],['journeys','route',t('journeys')],['bookings','bookings',t('bookings')],['inbox','inbox',t('inbox')],...communityNavigation()];
}
function publicPageNavigation(){
  const lang=state.lang==='te'?'te':'en';
  const labels=lang==='te'?['యాప్ గురించి','మీ ప్రశ్నలు']:['About the app','FAQs'];
  return `<a href="/welcome?lang=${lang}">${icon('route')}${labels[0]}</a><a href="/faq?lang=${lang}">${icon('chatCircleDots')}${labels[1]}</a>`;
}
function header(){
  const routes=roleNavigation();
  const brand=`<a class="brand brand-wordmark" href="#/${state.user?landingRoute():'login'}"><img class="brand-mark" src="/static/assets/seatpal/seat.svg" alt=""><span class="brand-copy"><span class="brand-title" lang="${state.lang==='te'?'te':'en'}">${t('name')}</span><small>${t('brandTagline')}</small></span></a>`;
  return `<header class="topbar hf-topbar ${state.user?'':'auth-topbar'}">${brand}<div class="header-controls">${languageSelect()}${state.user?`<button type="button" class="menu-toggle" data-action="menu-toggle" aria-label="${t('menu')}" aria-controls="account-menu" aria-expanded="${state.menuOpen}">${icon('user',24)}</button>`:''}</div>${state.user&&state.menuOpen?`<div class="header-menu" id="account-menu"><div class="header-account"><strong>${esc(state.user.name)}</strong><small>${isStaff()?t('roleStaff'):canDrive()?t('roleDriver'):t('roleMember')}</small></div><nav>${routes.map(([route,ico,label])=>`<a href="#/${route}" ${currentRoute()===route?'aria-current="page"':''}>${icon(ico)}${esc(label)}</a>`).join('')}${publicPageNavigation()}</nav><button type="button" class="menu-language text-button" data-language-choice="hi" lang="hi" aria-pressed="${state.lang==='hi'}">हिन्दी</button><button type="button" class="menu-signout" data-action="logout">${icon('back')}${t('logout')}</button></div>`:''}</header>`;
}

function shell(content){
  const navItems=roleNavigation(),route=currentRoute();
  const roleLabel=isStaff()?t('roleStaff'):canDrive()?t('roleDriver'):t('roleMember');
  const mobileItems=isStaff()?navItems:[['home','search',t('homeNav')],[canDrive()?'journeys':'bookings','bookings',canDrive()?t('journeys'):t('bookings')],['chats','chatCircleDots',t('communityChats')],['profile','user',t('communityProfile')]];
  const active=(r)=>r===route||(r==='home'&&['search-form','results','become-driver'].includes(route))||(r==='journeys'&&['drive-form','inbox'].includes(route))||(r==='bookings'&&route.startsWith('booking/'))||(r==='chats'&&route.startsWith('chat/'));
  return `${header()}<div class="layout hf-layout"><aside class="sidebar"><div class="actor"><span class="avatar">${esc((state.user?.name||'?').slice(0,1))}</span><div><strong>${esc(state.user?.name)}</strong><small>${roleLabel}</small></div></div><nav>${navItems.map(([r,ico,name])=>`<a href="#/${r}" class="${active(r)?'active':''}" ${active(r)?'aria-current="page"':''}>${icon(ico)}${esc(name)}</a>`).join('')}${publicPageNavigation()}</nav><button type="button" class="link-button signout" data-action="logout">${t('logout')}</button></aside><main class="main"><nav class="mobile-nav" aria-label="${t('menu')}">${mobileItems.map(([r,ico,name])=>`<a href="#/${r}" class="${active(r)?'active':''}" ${active(r)?'aria-current="page"':''}>${icon(ico)}<small>${esc(name)}</small></a>`).join('')}</nav>${route==='home'?festivalGreeting.html(state.lang,Boolean(state.user)):''}${state.error?`<div class="alert error" role="alert">${esc(errorMessage(state.error))} <button class="text-button" data-action="clear-message">${t('dismiss')}</button></div>`:''}${state.notice&&!(route==='results'&&state.noticeKey==='searchSaved')?`<div class="alert success" role="status">${esc(noticeText())}</div>`:''}${content}</main></div><footer class="safety">${safetyNotice()}</footer>`;
}
function locFields(name, initial={}) {const val=state.form?.values||{};const lat=initial.lat??val[`${name}_lat`],lon=initial.lon??val[`${name}_lon`],label=initial.label??val[`${name}_label`]??'';const has=Number.isFinite(Number(lat))&&Number.isFinite(Number(lon))&&lat!==''&&lon!=='';const selected=has?labelOf({lat:Number(lat),lon:Number(lon),label}):(label||t(name==='origin'?'choosePickup':'chooseDestination'));return `<fieldset class="location-field"><legend class="sr-only">${t(name)}</legend><button type="button" class="route-location-row map-pick-button" data-location="${name}" aria-label="${escAttr(`${t(name)}: ${selected}. ${t('mapChooseLocation')}`)}"><span class="route-stop-marker" aria-hidden="true">${icon('pin',24)}</span><span class="route-stop-label">${t(name)}</span><span class="route-stop-name" data-location-summary="${name}">${esc(selected)}</span><span class="route-stop-arrow" aria-hidden="true">›</span></button><input type="hidden" name="${name}_label" value="${escAttr(label)}"><input type="hidden" name="${name}_lat" value="${has?escAttr(lat):''}"><input type="hidden" name="${name}_lon" value="${has?escAttr(lon):''}"></fieldset>`}
function routeComposer({swap=false}={}){return `<div class="route-compose">${locFields('origin')}${swap?`<button type="button" class="route-swap-button" data-action="swap-route" aria-label="${t('swapLocations')}">${icon('swap',22)}</button>`:''}${locFields('destination')}</div>${state.landingIntentPending?`<p class="form-note route-confirmation-note" role="status">${t('chooseLocation')}</p>`:''}`}
function getPoint(form,name){let lat=Number(form.get(`${name}_lat`)),lon=Number(form.get(`${name}_lon`)),label=String(form.get(`${name}_label`)||'');if(!label||!Number.isFinite(lat)||!Number.isFinite(lon)||form.get(`${name}_lat`)===''||form.get(`${name}_lon`)==='')return null;const p=(state.boot?.places||[]).find(q=>Number(q.lat)===lat&&Number(q.lon)===lon);if(p&&(p.label===label||placeNames[state.lang]?.[p.label]===label))return {label:p.label,lat,lon};return {label,lat,lon}}
function syncLocationSummary(form,name,point){const summary=form.querySelector(`[data-location-summary="${name}"]`);summary.textContent=labelOf(point);const picker=form.querySelector(`[data-location="${name}"]`);picker.setAttribute('aria-label',`${t(name)}: ${labelOf(point)}. ${t('mapChooseLocation')}`);const quick=form.querySelector(`[data-quick-place="${name}"]`);if(quick)quick.value='';form.elements[`${name}_label`].value=point.label;form.elements[`${name}_lat`].value=point.lat;form.elements[`${name}_lon`].value=point.lon}
async function chooseLocation(form,name){const data=new FormData(form),current=getPoint(data,name),suggestion=String(data.get(`${name}_label`)||'').trim();try{const picker=pickLocation({title:t(name),initial:current,lang:state.lang,t,api});if(!current&&suggestion){const query=document.querySelector('.map-picker-dialog input[type="search"]');if(query)query.value=suggestion}const point=await picker;if(!point)return;syncLocationSummary(form,name,point);state.landingIntentPending=state.landingIntentPending&&!(getPoint(new FormData(form),'origin')&&getPoint(new FormData(form),'destination'));state.preview=null;captureDraft();render()}catch(err){setError(err);render()}}

function swapRoute(form){if(!form)return;for(const field of ['label','lat','lon']){const a=form.elements[`origin_${field}`],b=form.elements[`destination_${field}`],[oldA,oldB]=[a.value,b.value];a.value=oldB;b.value=oldA}state.preview=null;captureDraft();render()}
function timeField(name,key,value=''){return `<label class="field">${t(key)}<input type="datetime-local" name="${name}" value="${escAttr(value)}" required></label>`}
function numField(name,key,val,min=1,max=6){return `<label class="field">${t(key)}<input type="number" name="${name}" min="${min}" max="${max}" value="${val}" required inputmode="numeric"></label>`}
function loginPage(){return renderLogin({state,t,icon,escAttr,hostedBeta,phoneContent:phoneAuth.page(),legacyOpen:phoneAuth.legacyOpen,phoneBusy:phoneAuth.busy})}

function homePage(){return renderHome({state,t,icon,routeComposer})}

function roadNote(title,p,snap){if(!p)return '';const n=Number(snap);return `<p class="road-note"><b>${t(title)}:</b> ${esc(p.label||t('roadPoint'))}${Number.isFinite(n)&&n>0?` <span>· ${new Intl.NumberFormat(locale()).format(Math.round(n))} ${t('awayFromPoint')}</span>`:''}</p>`}
function routeAttribution(){return `<small class="route-credit">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></small>`}
function routeSvg(route){const coords=route?.coordinates;if(!Array.isArray(coords)||coords.length<2)return `<div class="route-empty">${t('noRoute')}</div>`;let lons=coords.map(c=>Number(c[0])),lats=coords.map(c=>Number(c[1]));let minx=Math.min(...lons),maxx=Math.max(...lons),miny=Math.min(...lats),maxy=Math.max(...lats);let dx=maxx-minx||0.001,dy=maxy-miny||0.001;let pts=coords.map(c=>`${18+(Number(c[0])-minx)/dx*264},${112-(Number(c[1])-miny)/dy*94}`).join(' ');let a=coords[0],b=coords.at(-1);return `<svg class="route-svg" viewBox="0 0 300 130" role="img" aria-label="${t('routeAria')}"><path d="M18 65H282" class="route-guide"/><polyline points="${pts}" class="route-line"/><circle cx="${18+(a[0]-minx)/dx*264}" cy="${112-(a[1]-miny)/dy*94}" r="5" class="route-start"/><circle cx="${18+(b[0]-minx)/dx*264}" cy="${112-(b[1]-miny)*94/dy}" r="5" class="route-end"/></svg>`}
function previewCard(p){if(!p)return '';let r=p.route||{};const rate=p.seat_rate_paise_per_km==null?t('priceNotListed'):inrPrecise(p.seat_rate_paise_per_km/100);return `<section class="panel preview-panel"><div class="section-row"><h2>${t('previewTitle')}</h2><span class="status-tag">${t('saved')}</span></div><div class="route-labels"><b>${esc(labelOf(p.origin))}</b><span>${t('toWord')}</span><b>${esc(labelOf(p.destination))}</b></div>${routeSvg(r)}<div class="stats-strip"><span><b>${r.distance_m?`${(r.distance_m/1000).toFixed(1)} km`:t('unknown')}</b><small>${t('distance')}</small></span><span><b>${dur(r.duration_s)}</b><small>${t('duration')}</small></span><span><b>${esc(r.provider||t('unknown'))}</b><small>${t('routeSource')}</small></span></div><p><b>${t('ratePerSeatKm')}:</b> ${esc(rate)} / ${t('km')} · ${t('rateIncludes')}</p>${routeAttribution()}${(()=>{const w=r.waypoints||[];return w.some(x=>Number(x.distance)>0)?`<div class="road-notes">${w[0]?roadNote('roadStart',{lat:w[0].location?.[1],lon:w[0].location?.[0]},w[0].distance):''}${w.at(-1)?roadNote('roadEnd',{lat:w.at(-1).location?.[1],lon:w.at(-1).location?.[0]},w.at(-1).distance):''}</div>`:''})()}<p class="success-copy">${t('previewSaved')}</p><button class="primary" data-action="publish" ${state.busy?'disabled':''}>${t('publish')}</button></section>`}
function driveForm(){return renderDriveForm({state,t,icon,routeComposer,seatStepper,escAttr,previewCard})}
function searchForm(){return renderSearchForm({state,t,icon,routeComposer,seatStepper,escAttr})}
function seatStepper(name,key,initial,min,max){const value=state.form?.values?.[name]||initial;return `<div class="field seat-stepper"><span>${t(key)}</span><div class="stepper-control"><button type="button" data-seat-step="-1" data-seat-field="${name}" aria-label="${t('decreaseSeats')}">${icon('minus',20)}</button><input type="number" name="${name}" min="${min}" max="${max}" value="${escAttr(value)}" required inputmode="numeric" aria-label="${t(key)}"><button type="button" data-seat-step="1" data-seat-field="${name}" aria-label="${t('increaseSeats')}">${icon('plus',20)}</button></div></div>`}
function statusName(s){return ({pending:t('pendingStatus'),accepted:t('accepted'),declined:t('declined'),cancelled:t('cancelled'),segment_completed:t('segmentDone'),published:t('statusPublished'),started:t('statusStarted'),completed:t('statusCompleted')})[s]||s||t('unknown')}
function checks(v={}){const pairs=[['phone',v.phone],['identity',v.identity],['dl',v.dl],['rc',v.rc],['selfie',v.selfie]];return `<div class="checks">${pairs.map(([k,val])=>`<span>${t(k)} <b class="check-state">${esc(val==='not_checked'?t('notChecked'):val||t('unknown'))}</b></span>`).join('')}</div>`}
function vehicleText(v){if(!v||typeof v!=='object')return v?String(v):t('vehicleUnknown');const parts=[v.model,v.plate].filter(Boolean);return parts.length?parts.join(' · '):t('vehicleUnknown')}
function matchCard(m){return `<article class="match-card"><div class="section-row"><div><h3>${esc(labelOf(m.pickup))} <span class="to">→</span> ${esc(labelOf(m.dropoff))}</h3><p class="muted">${t('pickup')}: ${fmtTime(m.pickup_at)} · ${esc(m.available_seats)} ${t('available')}</p></div><span class="status-tag">${t('noPayment')}</span></div>${roadNote('roadPickup',m.routed_pickup,m.pickup_snap_m)}${roadNote('roadDropoff',m.routed_dropoff,m.dropoff_snap_m)}<div class="detour-grid"><span>${t('pickupDetour')}<b>${minText(m.pickup_detour_minutes)}</b></span><span>${t('dropoffDetour')}<b>${minText(m.dropoff_detour_minutes)}</b></span><span>${t('totalDetour')}<b>${minText(m.total_driver_detour_minutes)}</b></span></div><p class="detour-note">${t('detourEstimate')}</p><div class="person-row"><div><b>${t('driver')}: ${esc(m.driver_name)}</b><small>${t('vehicle')}: ${esc(vehicleText(m.vehicle))}</small><small>${t('completedTrips')}: ${Number(m.driver_completed_trips||0)}</small></div><small>${esc(m.route_provider||t('unknown'))}</small></div><details><summary>${t('checks')}</summary>${checks(m.verification)}</details><button class="primary" data-action="request-seat" data-id="${escAttr(m.id)}" ${state.busy?'disabled':''}>${t('requestSeat')}</button></article>`}
function metricsBlock(m={}){let pairs=[['metricsTraditional','traditional_match_count'],['metricsAware','route_aware_match_count'],['metricsIncremental','incremental_matches'],['metricsLift','match_lift_percentage']];return `<div class="metric-grid">${pairs.map(([k,v])=>`<div><small>${t(k)}</small><b>${m[v]==null?'—':v==='match_lift_percentage'?`${Number(m[v]).toFixed(1)}%`:m[v]}</b></div>`).join('')}</div>${m.complete===false?`<p class="alert warning">${t('incomplete')} ${esc((m.evaluation_errors||[]).join('; '))}</p>`:''}<details class="baseline"><summary>${t('baseline')}</summary><p>${esc(m.baseline_definition||'')}</p></details>`}
function resultsPage(arg){return makeJourneyViews({state,t,icon,esc,escAttr,fmtTime,inr,minText,labelOf,statusName,routeSvg,routeAttribution,roadNote,localizedContribution,vehicleText,checks,locale}).resultsPage(arg)}
function tripCard(x){return `<article class="trip-row"><div><div class="route-labels"><b>${esc(labelOf(x.origin))}</b><span>${t('toWord')}</span><b>${esc(labelOf(x.destination))}</b></div><p>${fmtTime(x.departure)} · ${statusName(x.status)}</p></div><a class="secondary" href="#/trip/${encodeURIComponent(x.id)}">${t('journeyDetail')}</a></article>`}
function journeyPage(arg){return makeJourneyViews({state,t,icon,esc,escAttr,fmtTime,inr,minText,labelOf,statusName,routeSvg,routeAttribution,roadNote,localizedContribution,vehicleText,checks,locale}).journeyPage(arg)}
function bookingCard(arg){return makeJourneyViews({state,t,icon,esc,escAttr,fmtTime,inr,minText,labelOf,statusName,routeSvg,routeAttribution,roadNote,localizedContribution,vehicleText,checks,locale}).bookingCard(arg)}
function bookingPage(arg){return makeJourneyViews({state,t,icon,esc,escAttr,fmtTime,inr,minText,labelOf,statusName,routeSvg,routeAttribution,roadNote,localizedContribution,vehicleText,checks,locale}).bookingPage(arg)}
function inboxPage(arg){return makeJourneyViews({state,t,icon,esc,escAttr,fmtTime,inr,minText,labelOf,statusName,routeSvg,routeAttribution,roadNote,localizedContribution,vehicleText,checks,locale}).inboxPage(arg)}
function tripDetail(id){let tr=(state.data.trips||[]).find(x=>x.id===id);if(!tr)return `<div class="empty-state">${t('unknown')}</div>`;let inv=tr.inventory||[];let route=tr.current_route||tr.route;return `<section class="page-head"><div><button class="back" data-action="back">← ${t('back')}</button><h1>${t('journeyDetail')}</h1></div><span class="status-tag">${statusName(tr.status)}</span></section><section class="panel"><div class="route-labels"><b>${esc(labelOf(tr.origin))}</b><span>${t('toWord')}</span><b>${esc(labelOf(tr.destination))}</b></div><p>${fmtTime(tr.departure)}</p>${routeSvg(route)}<div class="stats-strip"><span><b>${route?.distance_m?`${new Intl.NumberFormat(locale(),{maximumFractionDigits:1}).format(route.distance_m/1000)} ${t('km')}`:t('unknown')}</b><small>${t('distance')}</small></span><span><b>${dur(route?.duration_s)}</b><small>${t('duration')}</small></span><span><b>${esc(route?.provider||'')}</b><small>${t('routeSource')}</small></span></div>${routeAttribution()}<div class="inventory"><h2>${t('segmentInventory')}</h2><p class="muted">${t('inventoryPosition')}</p>${inv.length?inv.map((s,i)=>`<div class="inventory-row"><span>${new Intl.NumberFormat(locale(),{maximumFractionDigits:1}).format((Number(s.from_m)/1000))}–${new Intl.NumberFormat(locale(),{maximumFractionDigits:1}).format((Number(s.to_m)/1000))} ${t('km')}</span><div class="seatbar" aria-label="${s.occupied} ${t('occupied')}, ${s.available} ${t('free')}"><i style="width:${Math.min(100,100*s.occupied/Math.max(1,s.occupied+s.available))}%"></i></div><b>${new Intl.NumberFormat(locale()).format(Number(s.occupied))} ${t('occupied')} / ${new Intl.NumberFormat(locale()).format(Number(s.available))} ${t('free')}</b></div>`).join(''):`<p>${t('noData')}</p>`}</div><div class="action-row">${tr.status==='published'?`<button class="primary" data-action="start-trip" data-id="${escAttr(tr.id)}" ${state.busy?'disabled':''}>${t('startTrip')}</button><button class="secondary" data-action="cancel-trip" data-id="${escAttr(tr.id)}" ${state.busy?'disabled':''}>${t('cancelTrip')}</button>`:''}${tr.status==='started'?`<button class="primary" data-action="complete-trip" data-id="${escAttr(tr.id)}" ${state.busy?'disabled':''}>${t('completeTrip')}</button>`:''}</div></section>`}
function livePage(id){return makeTripViews({state,t,icon,esc,escAttr,fmtTime,labelOf,bookingRouteMap}).livePage(id)}
function mountLivePage(){const element=app.querySelector('[data-live-booking]');if(!element)return;const id=element.dataset.liveBooking;if(state.liveCleanup&&state.liveBookingId===id&&state.liveElement===element)return;if(state.liveCleanup){state.liveCleanup();state.liveCleanup=null}const booking=(state.data.bookings||[]).find(x=>x.id===id);if(!booking)return;const trip=(state.data.trips||[]).find(x=>x.id===booking.trip_id);const liveBooking={...booking,route:booking.route||booking.trip_route||trip?.current_route||trip?.route};state.liveBookingId=id;state.liveElement=element;state.liveCleanup=mountLiveLocation({element,booking:liveBooking,viewerId:state.user?.id,lang:state.lang,t,api,labelPoint:labelOf,getCsrf:()=>state.csrf,onExpired:async()=>{await expireSession();render()}})}
function reportStatusName(v){return ({open:t('reportOpen'),resolved:t('reportResolved')})[v]||t('unknown')}
function safetyPage(id){return makeTripViews({state,t,icon,esc,escAttr,fmtTime,labelOf,bookingRouteMap}).safetyPage(id)}
function adminReports(rows=[]){const mayResolve=canResolveSafety();return `<section class="panel"><h2>${t('safetyReports')}</h2>${rows.length?rows.map(r=>`<article class="report-row"><div class="section-row"><b>${t(`category_${r.category}`)} · ${reportStatusName(r.status)}</b><small>${fmtTime(r.created_at)}</small></div><p>${esc(r.details)}</p>${r.resolution?`<p>${t('resolution')}: ${esc(r.resolution)}</p>`:mayResolve?`<form class="resolve-form" data-report-id="${escAttr(r.id)}"><label class="field">${t('resolution')}<textarea name="resolution" minlength="10" maxlength="1000" required rows="3">${esc(state.adminResolutionDrafts[r.id]||'')}</textarea></label><button type="button" class="secondary" data-action="resolve-report" data-id="${escAttr(r.id)}" ${state.busy?'disabled':''}>${t('resolveReport')}</button></form>`:''}</article>`).join(''):`<p>${t('noData')}</p>`}</section>`}
function bookingRouteMap(id){
  const booking=(state.data.bookings||[]).find(x=>x.id===id);if(!booking)return '';
  const trip=(state.data.trips||[]).find(x=>x.id===booking.trip_id);
  const route=booking.route||booking.trip_route||booking.match?.route||trip?.current_route||trip?.route;
  const points=[booking.match?.routed_pickup||booking.pickup,booking.match?.routed_dropoff||booking.dropoff].filter(Boolean);
  return `<div class="rating-route-map journey-map-shell"><div class="journey-map" data-journey-route-map data-route-coordinates="${escAttr(JSON.stringify(route?.coordinates||[]))}" data-route-points="${escAttr(JSON.stringify(points))}" aria-label="${t('routeAria')}"></div></div>`;
}
function ratePage(id){return makeTripViews({state,t,icon,esc,escAttr,fmtTime,labelOf,bookingRouteMap}).ratePage(id)}
function pct(v){return v==null?'—':`${Number(v).toFixed(1)}%`}
function operationsPage(){if(!canReadOps())return `<section class="panel"><h1>${t('operations')}</h1><p>${t('operationsUnavailable')}</p></section>`;let d=state.ops;if(!d)return `<div class="empty-state seatpal-wait-status" role="status" aria-busy="true">${busyMark()}<p>${t('loading')}</p></div>`;let m=d.metrics||{};let stats=[['users',d.users?.length],['trips',d.trips?.length],['requests',d.requests?.length],['matches',d.matches?.length],['ratings',d.ratings?.length],['events',d.events?.length],['safetyReports',(d.safety_reports||d.reports)?.length],['routes',d.route_calculations?.length]];let ms=[['metricsTraditional',m.traditional_match_count],['metricsAware',m.route_aware_match_count],['metricsIncremental',m.incremental_matches],['metricsLift',pct(m.match_lift_percentage)],['completeSearches',m.complete_searches],['matchedSearches',m.matched_searches],['acceptedBookings',m.accepted_bookings],['completedSegments',m.completed_segments],['completedTrips',m.completed_trips],['acceptance',pct(m.driver_acceptance_rate)],['conversion',pct(m.booking_conversion)],['metricDetour',m.median_driver_detour_minutes==null?'—':`${m.median_driver_detour_minutes} min`],['driverCancels',m.driver_cancellations],['passengerCancels',m.passenger_cancellations],['repeatDrivers',m.repeat_drivers],['repeatPassengers',m.repeat_passengers]];return `<section class="page-head"><div><h1>${t('adminTitle')}</h1><p class="muted">${t('developmentRows')}</p></div><button class="secondary" data-action="refresh">${t('refresh')}</button></section><div class="metric-grid">${stats.map(([k,v])=>`<div><small>${t(k)}</small><b>${v??0}</b></div>`).join('')}</div><section class="panel"><h2>${t('metrics')}</h2><div class="ops-metrics">${ms.map(([k,v])=>`<div><span>${t(k)}</span><b>${v??'—'}</b></div>`).join('')}</div><p class="baseline">${esc(m.baseline_definition||'')}</p></section>${adminReports(d.safety_reports||d.reports||[])}${[['users',d.users],['trips',d.trips],['requests',d.requests],['matches',d.matches],['bookings',d.bookings],['ratings',d.ratings],['events',d.events],['route_calculations',d.route_calculations]].map(([key,rows])=>tableSection(key,rows)).join('')}`}
function tableSection(key,rows=[]){let cols=Array.from(new Set((rows||[]).flatMap(o=>Object.keys(o||{})))).slice(0,8);return `<details class="table-section"><summary>${t(key)} <b>${rows?.length||0}</b></summary>${rows?.length?`<div class="table-wrap"><table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,i)=>`<tr>${cols.map(c=>`<td>${esc(typeof row[c]==='object'?JSON.stringify(row[c]):row[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:`<p>${t('noData')}</p>`}</details>`}
function setSharedRoutePoints(values){for(const name of ['origin','destination']){const lat=values?.[`${name}_lat`],lon=values?.[`${name}_lon`],label=values?.[`${name}_label`];state.routePoints[name]=label&&lat!==''&&lon!==''&&Number.isFinite(Number(lat))&&Number.isFinite(Number(lon))?{label,lat:Number(lat),lon:Number(lon)}:null}}
function sharedRouteValues(){const out={};for(const name of ['origin','destination']){const p=state.routePoints[name];if(p){out[`${name}_label`]=p.label;out[`${name}_lat`]=p.lat;out[`${name}_lon`]=p.lon}}return out}
function prepareComposerDraft(id){const base=state.formDrafts[id]||{id,values:{}};state.form={id,values:{...(base.values||{}),...sharedRouteValues()}}}
function openComposer(id){if(id==='drive-form'&&!canDrive()){captureDraft();state.menuOpen=false;nav('become-driver');return}captureDraft();const values={...(state.formDrafts[id]?.values||{}),...sharedRouteValues()};state.formDrafts[id]={id,values};state.form={id,values};state.menuOpen=false;nav(id)}
function captureDraft(){if(state.skipCaptureOnce){state.skipCaptureOnce=false;return}const form=app.querySelector('form#home-route-form,form#drive-form,form#search-form,form#rate-form,form#login-form,form#safety-form');if(!form)return;const out={id:form.id,entityId:form.dataset.id||'',values:{}};new FormData(form).forEach((v,k)=>out.values[k]=v);state.form=out;if(['rate-form','safety-form'].includes(form.id))state.formDrafts[`${form.id}:${out.entityId}`]=out;if(['home-route-form','drive-form','search-form'].includes(form.id)){state.formDrafts[form.id]=out;setSharedRoutePoints(out.values)}}
function restoreDraft(){const scoped=app.querySelector('#rate-form,#safety-form');const d=scoped?state.formDrafts[`${scoped.id}:${scoped.dataset.id||''}`]:state.form;if(!d)return;const form=document.getElementById(d.id);if(!form)return;if(['rate-form','safety-form'].includes(d.id)&&d.entityId!==(form.dataset.id||''))return;for(const [k,v] of Object.entries(d.values)){const el=form.elements[k];if(el){if(el.type==='checkbox')el.checked=Boolean(v);else el.value=d.id==='search-form'&&k==='seats'?'1':v}}for(const name of ['origin','destination']){const label=form.elements[`${name}_label`],lat=Number(form.elements[`${name}_lat`]?.value),lon=Number(form.elements[`${name}_lon`]?.value);const preset=(state.boot?.places||[]).find(p=>Number(p.lat)===lat&&Number(p.lon)===lon&&p.label===label?.value);if(preset&&placeNames[state.lang]?.[preset.label])label.value=placeNames[state.lang][preset.label]}}
function mountJourneyMapForView(){
  const cleanups=[];
  const element=app.querySelector('#journey-map');
  if(element){
    const form=app.querySelector('#home-route-form,#drive-form,#search-form');
    const points=form?['origin','destination'].map(name=>getPoint(new FormData(form),name)).filter(Boolean):[];
    cleanups.push(mountJourneyMap(element,{points,route:currentRoute()==='drive-form'?state.preview?.route:undefined,lang:state.lang,t}));
  }
  for(const mapElement of app.querySelectorAll('[data-journey-route-map]')){
    let coordinates=[],points=[];
    try{coordinates=JSON.parse(mapElement.dataset.routeCoordinates||'[]');points=JSON.parse(mapElement.dataset.routePoints||'[]')}catch{}
    if(!Array.isArray(coordinates))coordinates=[];if(!Array.isArray(points))points=[];
    cleanups.push(mountJourneyMap(mapElement,{points,route:{coordinates},lang:state.lang,t}));
  }
  state.journeyMapCleanup=()=>cleanups.forEach(dispose=>dispose());
}
function appendTripOfferSnapshot(route){
  if(!route.startsWith('trip/'))return;
  const trip=state.data.trips.find(row=>row.id===decodeURIComponent(route.slice(5)));
  const target=app.querySelector('.inventory');
  if(!trip||!target)return;
  const legacyPrice=trip.seat_rate_paise_per_km==null&&Number.isInteger(trip.seat_price_paise);
  const price=trip.seat_rate_paise_per_km!=null?inrPrecise(trip.seat_rate_paise_per_km/100):legacyPrice?inrPrecise(trip.seat_price_paise/100):t('priceNotListed');
  const capacity=trip.baggage_capacity?`${Number(trip.baggage_capacity.small_bags)===1?t('oneSmallBag'):t('smallBagCount').replace('{count}',new Intl.NumberFormat(locale()).format(trip.baggage_capacity.small_bags))} · ${Number(trip.baggage_capacity.large_suitcases)===1?t('oneLargeSuitcase'):t('largeSuitcaseCount').replace('{count}',new Intl.NumberFormat(locale()).format(trip.baggage_capacity.large_suitcases))}`:t('bagCapacityUnknown');
  const ac=trip.comfort?.air_conditioning==='yes'?t('acDeclaredYes'):trip.comfort?.air_conditioning==='no'?t('acDeclaredNo'):t('acNotSpecified');
  const panel=document.createElement('section');panel.className='panel trip-offer-snapshot';
  panel.innerHTML=`<h2>${t('publishedOfferDetails')}</h2><div class="stats-strip"><span><b>${esc(price)}${legacyPrice?'':` / ${t('km')}`}</b><small>${legacyPrice?t('legacyFixedFare'):t('ratePerPassengerRouteKm')}</small></span><span><b>${esc(ac)}</b><small>${t('airConditioning')} · ${t('driverDeclared')}</small></span><span><b>${esc(capacity)}</b><small>${t('spaceAfterDriverBags')}</small></span></div>${legacyPrice?'':`<p>${t('rateIncludes')}</p>`}${trip.baggage_notes?`<p><b>${t('tripBaggageNotes')}:</b> ${esc(trip.baggage_notes)}</p>`:''}`;
  target.insertAdjacentElement('beforebegin',panel);
}
function render(){
  community.unmount?.();accountFlows.unmount();identityFlows.unmount();phoneAuth.unmount();
  (state.tripSharingCleanups || []).forEach((cleanup) => cleanup());
  state.tripSharingCleanups = [];
  captureDraft();
  if(state.journeyMapCleanup){state.journeyMapCleanup();state.journeyMapCleanup=null}
  document.documentElement.lang=state.lang;
  document.title=t('documentTitle');
  const r=currentRoute();
  if(state.user){
    const requested=location.hash.replace(/^#\/?/,'');
    if(requested!==r)history.replaceState(history.state,'',`${location.pathname}${location.search}#/${r}`);
    if(r==='home')prepareComposerDraft('home-route-form');
    else if(r==='drive-form')prepareComposerDraft('drive-form');
    else if(r==='search-form')prepareComposerDraft('search-form');
  }
  state.renderedRoute=r;
  if(state.logoutPending){
    const copy=sessionCopy();
    const retry=state.logoutChangedAccount?`<p class="alert warning" role="alert">${copy.different}</p><button type="button" class="primary" data-action="continue-current-session">${copy.continue}</button>`:state.logoutFailed?`<p class="alert error" role="alert">${copy.failed}</p><button type="button" class="primary" data-action="retry-signout" ${state.logoutRetrying?'disabled':''}>${state.logoutRetrying?t('pending'):copy.retry}</button>`:`<p class="loading" role="status" aria-live="polite">${t('pending')}</p>`;
    app.innerHTML=header()+`<main class="main logged-out"><section class="panel" aria-live="polite"><h1>${copy.title}</h1>${retry}</section></main>`;
    wire();return;
  }
  if(state.sessionSyncing){
    const copy=sessionCopy();app.innerHTML=header()+`<main class="main logged-out"><section class="panel" role="status" aria-live="polite"><h1>${copy.checking}</h1><p>${state.sessionSyncFailed?copy.checkFailed:''}</p>${state.sessionSyncFailed?`<button type="button" class="primary" data-action="retry-session-check">${copy.retry}</button>`:`<p class="loading">${t('pending')}</p>`}</section></main>`;
    wire();return;
  }
  if(!state.boot){
    app.innerHTML=header()+`<main class="main logged-out">${state.error?`<div class="alert error" role="alert">${esc(errorMessage(state.error))} <button class="text-button" data-action="retry-bootstrap">${t('retry')}</button></div>`:`<div class="loading seatpal-bootstrap" role="status" aria-busy="true">${busyMark()}${t('loading')}</div>`}</main>`;
    wire();return;
  }
  if(!state.user){
    app.innerHTML=header()+`<main class="main logged-out">${state.error?`<div class="alert error" role="alert">${esc(errorMessage(state.error))}</div>`:''}${state.notice?`<p class="alert success" role="status">${esc(noticeText())}</p>`:''}${loginPage()}</main><footer class="safety">${safetyNotice()}</footer>`;
    restoreDraft();wire();paintPending();phoneAuth.mount(app,'login');return;
  }
  if(state.user.onboarding_required===true){app.innerHTML=header()+`<main class="main logged-out">${state.error?`<p class="alert error">${esc(errorMessage(state.error))}</p>`:''}${phoneAuth.page(true)}</main>`;wire();phoneAuth.mount(app,'onboarding');return;}
  let content='';
  if(identityFlows.owns(r))content=identityFlows.page(r);
  else if(accountFlows.owns(r))content=accountFlows.page(r);
  else if(r==='home')content=homePage();
  else if(r==='drive-form')content=driveForm();
  else if(r==='become-driver')content=renderBecomeDriver({state,t,icon});
  else if(r==='search-form')content=searchForm();
  else if(r==='results')content=resultsPage();
  else if(r==='journeys')content=journeyPage();
  else if(r==='bookings')content=bookingPage();
  else if(r==='inbox')content=inboxPage();
  else if(r==='profile')content=community.profilePage();
  else if(r==='chats')content=community.chatsPage();
  else if(r==='notifications')content=community.notificationsPage();
  else if(r.startsWith('chat/'))content=community.chatPage(decodeURIComponent(r.slice(5)));
  else if(r.startsWith('complete/'))content=makeTripViews({state,t,icon,esc,escAttr,fmtTime,labelOf,bookingRouteMap}).completedTripPage(decodeURIComponent(r.slice(9)))||bookingPage();
  else if(r.startsWith('trip/'))content=tripDetail(decodeURIComponent(r.slice(5)));
  else if(r.startsWith('rate/'))content=ratePage(decodeURIComponent(r.slice(5)));
  else if(r.startsWith('live/'))content=livePage(decodeURIComponent(r.slice(5)));
  else if(r.startsWith('safety/'))content=safetyPage(decodeURIComponent(r.slice(7)));
  else if(r==='operations'&&isStaff())content=operationsPage();
  else content=homePage();
  ensureFestivalGreetingStyles();app.innerHTML=shell(content);
  appendTripOfferSnapshot(r);
  restoreDraft();wire();initJourneyTimeInputs();paintPending();mountJourneyMapForView();
  const isLive=currentRoute().startsWith('live/');
  if(state.liveCleanup&&(!isLive||state.liveElement?.isConnected===false)){state.liveCleanup();state.liveCleanup=null;state.liveBookingId=null;state.liveElement=null}
  if(isLive)mountLivePage();
  for (const element of app.querySelectorAll('[data-trip-sharing]')) {
    state.tripSharingCleanups.push(mountTripSharing({element,bookingId:element.dataset.bookingId,api,lang:state.lang,t,viewerId:state.user?.id||''}));
  }
  community.mount?.({root:app,view:r.startsWith('chat/')?'chat':r,bookingId:r.startsWith('chat/')?decodeURIComponent(r.slice(5)):''});
  accountFlows.mount(app,r);identityFlows.mount(app,r);phoneAuth.mount(app,r);
}
function wire(){document.querySelectorAll('form [required]').forEach(el=>{el.addEventListener('invalid',ev=>{const v=ev.target.validity;if(v.customError)return;ev.target.setCustomValidity(v.valueMissing?t('required'):v.badInput?t('invalidNumber'):v.rangeOverflow||v.rangeUnderflow?t('rangeInvalid'):v.tooShort||v.tooLong?(ev.target.form?.classList.contains('resolve-form')?t('invalidResolution'):ev.target.form?.id==='safety-form'?t('invalidReportDetails'):t('required')):ev.target.type==='datetime-local'?t('invalidDate'):t('required'))});['input','change'].forEach(type=>el.addEventListener(type,()=>el.setCustomValidity('')))});document.querySelector('[name="seat_rate_rupees_per_km"]')?.addEventListener('input',event=>event.target.setCustomValidity(''));document.querySelectorAll('[data-fare-review]').forEach(panel=>panel.addEventListener('toggle',()=>{state.fareReviewId=panel.open?panel.dataset.fareReview:null}));document.querySelector('#language')?.addEventListener('change',e=>{captureDraft();changeLanguage(e.target.value);render()});document.querySelectorAll('[data-language-choice]').forEach(button=>button.addEventListener('click',()=>{const select=document.querySelector('#language');if(!select)return;select.value=button.dataset.languageChoice;select.dispatchEvent(new Event('change',{bubbles:true}))}));document.querySelector('#login-form')?.addEventListener('submit',login);document.querySelector('#drive-form')?.addEventListener('submit',preview);document.querySelector('#search-form')?.addEventListener('submit',search);document.querySelector('#rate-form')?.addEventListener('submit',rate);document.querySelector('#safety-form')?.addEventListener('submit',submitSafety);document.querySelectorAll('[data-location]').forEach(b=>b.addEventListener('click',()=>chooseLocation(b.closest('form'),b.dataset.location)));document.querySelectorAll('[data-account-choice]').forEach(b=>b.addEventListener('click',()=>{const select=document.querySelector('#account-choice');if(!select)return;select.value=b.dataset.accountChoice;document.querySelectorAll('[data-account-choice]').forEach(x=>{const selected=x===b;x.classList.toggle('selected',selected);x.setAttribute('aria-pressed',String(selected))})}));document.querySelectorAll('[data-seat-step]').forEach(b=>b.addEventListener('click',()=>{const input=b.closest('.stepper-control')?.querySelector(`input[name="${CSS.escape(b.dataset.seatField)}"]`);if(!input)return;const min=Number(input.min||1),max=Number(input.max||6),value=Math.max(min,Math.min(max,Number(input.value||min)+Number(b.dataset.seatStep)));input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))}));document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>act(b.dataset.action,b.dataset.id)));}
function pendingButton(button,label){
  if(!button||button.dataset.seatpalPending)return;
  const before=button.innerHTML;
  beginBusy(button,label,state.pendingUi?.startedAt);
  button.dataset.before=before;
}
function paintPending(){
  const pending=state.pendingUi;if(!state.busy||!pending)return;
  const button=pending.formId?app.querySelector(`#${CSS.escape(pending.formId)} button[type=submit],#${CSS.escape(pending.formId)} button:not([type])`):app.querySelector(`[data-action="${CSS.escape(pending.action)}"]${pending.id?`[data-id="${CSS.escape(pending.id)}"]`:''}`);
  for(let details=button?.closest('details');details;details=details.parentElement?.closest('details'))details.open=true;
  pendingButton(button,`${button?.textContent.trim()||t('pending')} · ${t('loading')}`);
}
function markPending(form,label){state.pendingUi={formId:form.id,startedAt:Date.now()};paintPending()}
function clearPending(){state.pendingUi=null;app.querySelectorAll('button[data-seatpal-pending]').forEach(button=>{button.innerHTML=button.dataset.before;button.disabled=false;button.removeAttribute('aria-busy');delete button.dataset.before;delete button.dataset.seatpalPending})}
function resetAccountState(){
  community.destroy();accountFlows.destroy();identityFlows.destroy();phoneAuth.destroy();clearTripSharingState();
  if(state.liveCleanup){state.liveCleanup();state.liveCleanup=null}
  state.liveBookingId=null;state.liveElement=null;
  if(state.journeyMapCleanup){state.journeyMapCleanup();state.journeyMapCleanup=null}
  state.sessionVersion++;
  state.boot=null;state.csrf='';state.user=null;
  state.data={trips:[],bookings:[],requests:[],ratings:[]};state.preview=null;state.results=null;state.resultsMode='best';state.ops=null;state.fareReviewId=null;
  state.form=null;state.formDrafts={};state.routePoints={origin:null,destination:null};state.blockConfirm=null;state.reportKeys={};state.adminResolutionDrafts={};
  state.menuOpen=false;state.passwordVisible=false;state.busy=false;state.pendingUi=null;state.error='';state.notice='';state.noticeKey=null;state.skipCaptureOnce=true;
}
async function revalidateSession({remoteChange=false}={}){
  if(state.logoutPending)return;
  if(state.sessionSyncing&&!remoteChange&&!state.sessionSyncFailed)return;
  const oldUserId=state.user?.id||null;
  if(remoteChange)resetAccountState();
  else{state.sessionVersion++;state.skipCaptureOnce=true;}
  state.sessionSyncing=true;state.sessionSyncFailed=false;state.error='';state.notice='';
  let version=state.sessionVersion;
  render();
  try{
    const boot=await api('/api/bootstrap');
    if(version!==state.sessionVersion||state.logoutPending)return;
    const changed=remoteChange||(boot.user?.id||null)!==oldUserId;
    if(changed&&!remoteChange){resetAccountState();state.sessionSyncing=true;version=state.sessionVersion;}
    state.boot=boot;state.csrf=boot.csrf_token||'';state.user=boot.user||null;
    if(state.user)await refreshState({forceSessionSync:true});
    if(version!==state.sessionVersion||state.logoutPending)return;
    state.sessionSyncing=false;state.sessionSyncFailed=false;state.error='';
    if(changed)nav(state.user?(state.user.onboarding_required?'phone-profile':landingRoute()):'login');
    render();
  }catch(error){
    if(version!==state.sessionVersion||state.logoutPending||error?.code==='stale_session_response')return;
    state.sessionSyncing=true;state.sessionSyncFailed=true;render();
  }
}
async function accountDeleted(){await expireSession();sessionCoordinator.announce();state.error='';setNotice(t('lcDeleted'));nav('login');render();}
async function beginLogout(){
  if(state.logoutPending||!state.user)return;
  state.logoutAttempt={userId:state.user.id,csrf:state.csrf};
  state.logoutPending=true;state.logoutRetrying=false;state.logoutFailed=false;state.logoutChangedAccount=false;
  resetAccountState();state.logoutPending=true;state.logoutRetrying=false;
  render();await retryLogout();
}
async function retryLogout(){
  if(!state.logoutPending||state.logoutRetrying||!state.logoutAttempt)return;
  const attempt=state.logoutAttempt;
  state.logoutRetrying=true;state.logoutFailed=false;render();
  try{
    await api('/api/logout','POST',{}, {expectedUserId:attempt.userId,csrf:attempt.csrf,allowLogout:true});
    if(state.logoutAttempt!==attempt)return;
    state.logoutPending=false;state.logoutRetrying=false;state.logoutFailed=false;state.logoutAttempt=null;
    resetAccountState();sessionCoordinator.announce();
    try{await loadBootstrap()}catch(error){state.error=error;}
    nav('login');render();
  }catch(error){
    if(state.logoutAttempt!==attempt)return;
    try{
      const boot=await api('/api/bootstrap','GET',undefined,{allowLogout:true});
      if(state.logoutAttempt!==attempt)return;
      if(!boot.user){state.logoutPending=false;state.logoutRetrying=false;state.logoutFailed=false;state.logoutAttempt=null;resetAccountState();sessionCoordinator.announce();state.boot=boot;state.csrf=boot.csrf_token||'';nav('login');render();return}
      if(boot.user.id!==attempt.userId){state.logoutChangedAccount=true;state.logoutFailed=false;state.logoutRetrying=false;render();return}
    }catch{}
    state.logoutRetrying=false;state.logoutFailed=true;render();
  }
}
async function continueCurrentSession(){state.logoutPending=false;state.logoutChangedAccount=false;state.logoutFailed=false;state.logoutRetrying=false;state.logoutAttempt=null;resetAccountState();try{await loadBootstrap();if(state.user)await refreshState();nav(state.user?(state.user.onboarding_required?'phone-profile':landingRoute()):'login')}catch(error){setError(error)}render()}
function landingIntentRoute(fallback){if(!state.user||state.user.onboarding_required===true)return fallback;const intent=consumeLandingIntent();if(!intent||isStaff())return fallback;const id=intent.intent==='offer'?'drive-form':'search-form';state.formDrafts[id]={id,values:{origin_label:intent.originLabel||'',destination_label:intent.destinationLabel||''}};state.form={...state.formDrafts[id]};state.routePoints={origin:null,destination:null};state.landingIntentPending=true;return routeForUser(id)}
async function phoneAuthenticated(out){resetAccountState();state.user=out.user;state.csrf=out.csrf_token||'';sessionCoordinator.announce();try{await loadBootstrap();if(!state.user?.onboarding_required)await refreshState();nav(landingIntentRoute(state.user?.onboarding_required?'phone-profile':'home'));}catch(error){setError(error);}finally{render();}}
async function phoneProfileSaved(out){state.user=out.user;state.form=null;state.formDrafts={};state.error='';state.skipCaptureOnce=true;try{await refreshState();nav(landingIntentRoute('home'));}catch(error){setError(error);}finally{render();}}
async function login(e){e.preventDefault();if(state.busy||phoneAuth.busy||state.logoutPending||state.sessionSyncing)return;let f=new FormData(e.target);state.busy=true;markPending(e.target,t('pending'));try{let out=await api('/api/login','POST',{account:f.get('account'),password:f.get('password')});resetAccountState();await loadBootstrap();if(!state.user)throw new Error('Sign-in could not be confirmed. Retry.');sessionCoordinator.announce();await refreshState();state.notice='';state.noticeKey=null;state.error='';const landing=landingIntentRoute(landingRoute());if(landing==='operations'&&canReadOps())await loadOps();nav(landing)}catch(err){if(err.status===401&&err.path!=='/api/login')await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
function initJourneyTimeInputs(){
  const form=document.querySelector('#search-form,#drive-form'); if(!form)return;
  const start=form.elements.window_start,end=form.elements.window_end,departure=form.elements.departure;
  seedBlankJourneyTimes({start,end,departure});
  if(start&&end){
    const base=bindPickupWindow(start,end,{t});
    const arrive=form.elements.arrive_by;
    const validate=()=>{
      const result=base.validate();
      if(arrive){
        arrive.setCustomValidity('');
        if(arrive.value&&start.value&&arrive.value<start.value)arrive.setCustomValidity(t('arriveByBeforePickup'));
        if(start.value)arrive.min=start.value;
        const endBounds=seedJourneyTimes(); if(endBounds.max)arrive.max=endBounds.max;
        return {valid:result.valid&&arrive.validity.valid,errorKey:arrive.validity.customError?'arriveByBeforePickup':result.errorKey};
      }
      return result;
    };
    form.journeyTimes={validate};
    for(const input of [start,end,arrive].filter(Boolean))for(const event of ['focus','input','change'])input.addEventListener(event,validate);
  }
  else if(departure){
    const refresh=()=>{const bounds=seedJourneyTimes();departure.min=bounds.min;departure.max=bounds.max;const result=validateJourneyTime(departure.value);departure.setCustomValidity(result.valid?'':t(result.errorKey));return result};
    for(const event of ['focus','input','change'])departure.addEventListener(event,refresh);
    form.journeyTimes={validate:refresh};refresh();
  }
  for(const input of [start,end,departure,form.elements.arrive_by].filter(Boolean)){
    let note=form.querySelector(`#${input.name}-error`);
    if(!note){note=document.createElement('small');note.className='field-error';note.setAttribute('aria-live','polite');note.id=`${input.name}-error`;input.closest('label').append(note)}
    const describedBy=new Set((input.getAttribute('aria-describedby')||'').split(/\s+/).filter(Boolean));describedBy.add(note.id);input.setAttribute('aria-describedby',[...describedBy].join(' '));
    input.addEventListener('input',()=>{note.textContent='';input.removeAttribute('aria-invalid')});
  }
}
function validateJourneyTimeForm(form){
  form.journeyTimes?.validate();
  const valid=form.reportValidity();
  for(const input of form.querySelectorAll('input[type="datetime-local"]')){
    const note=form.querySelector(`#${input.name}-error`);if(note)note.textContent=input.validationMessage;
    input.setAttribute('aria-invalid',String(!input.validity.valid));
  }
  return valid;
}
function localIso(v){if(!v)throw new Error('Enter a date and time.');return `${v}:00+05:30`}
function searchExpired(results=state.results){const saved=Date.parse(results?.saved_at||results?.request?.created_at||'');return Number.isFinite(saved)&&Date.now()-saved>20*60*1000}
function requestDraftFromSaved(request={}){const local=value=>{if(!value)return '';const d=new Date(value);return Number.isNaN(d.getTime())?'':new Date(d.getTime()+330*60000).toISOString().slice(0,16)};const vals={window_start:local(request.window_start),window_end:local(request.window_end),arrive_by:local(request.arrive_by),seats:'1',baggage_small_bags:String(request.baggage?.small_bags??0),baggage_large_suitcases:String(request.baggage?.large_suitcases??0),baggage_notes:request.baggage_notes||''};for(const name of ['origin','destination']){const point=request[name]||{};vals[`${name}_label`]=point.label||'';vals[`${name}_lat`]=point.lat==null?'':String(point.lat);vals[`${name}_lon`]=point.lon==null?'':String(point.lon)}return {id:'search-form',values:vals}}
function searchPayload(values){
  const getPointValue=name=>values[`${name}_label`]&&values[`${name}_lat`]!==''&&values[`${name}_lon`]!==''?{label:values[`${name}_label`],lat:Number(values[`${name}_lat`]),lon:Number(values[`${name}_lon`])}:null;
  const when=value=>value?(/(?:Z|[+-]\d\d:\d\d)$/.test(value)?value:localIso(value)):null;
  return {origin:getPointValue('origin'),destination:getPointValue('destination'),window_start:when(values.window_start),window_end:when(values.window_end),arrive_by:when(values.arrive_by),seats:1,baggage:{small_bags:Number(values.baggage_small_bags||0),large_suitcases:Number(values.baggage_large_suitcases||0)},baggage_notes:String(values.baggage_notes||'').replace(/[\u0000-\u001f\u007f-\u009f]/g,' ').trim()};
}
function driverPreviewPayload(f){
  const rateRaw=String(f.get('seat_rate_rupees_per_km')??'').trim();
  const ratePaise=rateRaw===''?null:rupeesToPaise(rateRaw);
  const capacityKnown=f.has('baggage_capacity_known');
  return {origin:getPoint(f,'origin'),destination:getPoint(f,'destination'),departure:localIso(f.get('departure')),seats:Number(f.get('seats')),max_detour_minutes:Number(f.get('max_detour_minutes')),
    seat_rate_paise_per_km:ratePaise,
    comfort:{air_conditioning:f.get('air_conditioning')||'unknown'},
    baggage_capacity:capacityKnown?{small_bags:Number(f.get('capacity_small_bags')),large_suitcases:Number(f.get('capacity_large_suitcases'))}:null,
    baggage_notes:String(f.get('baggage_notes')||'').replace(/[\u0000-\u001f\u007f-\u009f]/g,' ').trim()};
}
function rupeesToPaise(value){const m=String(value).match(/^(\d+)(?:\.(\d{1,2}))?$/);if(!m) return null;const rupees=Number(m[1]),fraction=Number((m[2]||'').padEnd(2,'0')||0);const total=rupees*100+fraction;return Number.isSafeInteger(total)&&total<=10000000?total:null}
async function preview(e){e.preventDefault();if(state.busy)return;if(!validateJourneyTimeForm(e.target))return;const f=new FormData(e.target);if(!getPoint(f,'origin')||!getPoint(f,'destination')){setError(t('chooseLocation'));e.target.querySelector('[data-location]')?.focus();render();return}const rateValue=String(f.get('seat_rate_rupees_per_km')??'').trim();if(rateValue!==''&&rupeesToPaise(rateValue)==null){const rateInput=e.target.elements.seat_rate_rupees_per_km;rateInput.setCustomValidity(t('invalidRate'));rateInput.reportValidity();rateInput.focus();return}state.busy=true;markPending(e.target,t('pending'));try{const out=await api('/api/preview','POST',driverPreviewPayload(f));state.preview=out.preview;setNotice(t('previewSaved'))}catch(err){if(err.status===401)await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
async function search(e){e.preventDefault();if(state.busy)return;if(!validateJourneyTimeForm(e.target))return;const f=new FormData(e.target);if(!getPoint(f,'origin')||!getPoint(f,'destination')){setError(t('chooseLocation'));e.target.querySelector('[data-location]')?.focus();render();return}const actorId=state.user?.id;const savedSearchDraft={id:e.target.id,values:Object.fromEntries(f.entries())};state.busy=true;markPending(e.target,t('pending'));try{const out=await api('/api/search','POST',searchPayload(Object.fromEntries(f.entries())));state.results={...out,saved_search:true,saved_at:out.saved_at||out.request?.created_at||new Date().toISOString()};state.resultsMode='best';state.fareReviewId=null;await refreshState();state.form=state.user?.id===actorId?savedSearchDraft:null;if(state.form)state.formDrafts['search-form']=state.form;setNotice('Search saved.');nav('results')}catch(err){if(err.status===401)await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
async function rate(e){e.preventDefault();if(state.busy)return;let f=new FormData(e.target);state.busy=true;markPending(e.target,t('pending'));try{await api('/api/rate','POST',{booking_id:e.target.dataset.id,stars:Number(f.get('stars')),comment:f.get('comment'),publish_comment:f.has('publish_comment')});delete state.formDrafts[`rate-form:${e.target.dataset.id}`];state.form=null;state.skipCaptureOnce=true;setNotice(t('rateSubmitted'));await refreshState();nav('bookings')}catch(err){if(err.status===401)await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
async function submitSafety(e){e.preventDefault();if(state.busy)return;const f=new FormData(e.target);const bookingId=e.target.dataset.id;const key=state.reportKeys[bookingId]||(crypto.randomUUID?crypto.randomUUID():`${Date.now()}-${Math.random().toString(36).slice(2)}`);state.reportKeys[bookingId]=key;state.busy=true;markPending(e.target,t('pending'));try{await api('/api/report_safety','POST',{booking_id:e.target.dataset.id,category:f.get('category'),details:f.get('details'),idempotency_key:key});await refreshState();delete state.reportKeys[bookingId];delete state.formDrafts[`safety-form:${bookingId}`];state.form=null;state.skipCaptureOnce=true;setNotice(t('reportSent'))}catch(err){if(err.status===401)await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
async function refreshState({forceSessionSync=false}={}){if(!state.user||state.logoutPending||(state.sessionSyncing&&!forceSessionSync))return;if(state.user.onboarding_required===true)return {user:state.user};let d=await api('/api/state');if(d.user?.id!==state.user.id){await revalidateSession({remoteChange:true});throw Object.assign(new Error('The session changed while the request was in progress.'),{status:409,code:'stale_session_response'});}state.user=d.user||state.user;state.data={...state.data,...d};if(!state.results&&!state.form&&currentRoute()==='results'&&d.latest_search?.saved_search){state.results=d.latest_search;state.resultsMode='best'}return d}
async function loadOps(){if(!canReadOps()){state.ops=null;return}state.ops=await api('/api/operations')}
async function act(action,id){if(action==='logout'){void beginLogout();return}if(action==='retry-signout'){void retryLogout();return}if(action==='continue-current-session'){void continueCurrentSession();return}if(action==='retry-session-check'){void revalidateSession();return}if(state.logoutPending||state.sessionSyncing||state.busy)return;if(action==='festival-dismiss'){if(festivalGreeting.dismiss(id))render();return}if(action==='request-seat'){const match=state.results?.matches?.find(row=>row.id===id);if(state.fareReviewId!==id||!hasRequestableQuote(match?.price_quote)){setError(t(state.fareReviewId===id?'fareUnavailable':'reviewFareFirst'));render();return}}if(action==='resolve-report'&&!canResolveSafety()){setError({status:403,message:'forbidden'});render();return}const resolveForm=action==='resolve-report'?document.querySelector(`.resolve-form[data-report-id="${CSS.escape(id)}"]`):null;if(resolveForm&&!resolveForm.reportValidity())return;const resolutionText=resolveForm?new FormData(resolveForm).get('resolution'):null;if(action==='resolve-report')state.adminResolutionDrafts[id]=resolutionText;state.error='';state.notice='';try{if(action==='use-telugu'){captureDraft();changeLanguage('te');render();return}if(action==='menu-toggle'){state.menuOpen=!state.menuOpen;render();return}if(action==='password-toggle'){const input=document.querySelector('#login-password'),button=document.querySelector('[data-action="password-toggle"]');if(input&&button){state.passwordVisible=!state.passwordVisible;input.type=state.passwordVisible?'text':'password';button.setAttribute('aria-label',t(state.passwordVisible?'hidePassword':'showPassword'));button.innerHTML=icon(state.passwordVisible?'eyeSlash':'eye',24)}return}if(action==='home-search'){openComposer('search-form');return}if(action==='home-drive'){openComposer('drive-form');return}if(action==='swap-route'){swapRoute(document.querySelector('#home-route-form, #search-form, #drive-form'));return}if(action==='retry-bootstrap'){state.busy=true;state.error='';render();try{await loadBootstrap();state.error='';if(state.user)await refreshState()}catch(e){setError(e)}finally{state.busy=false;render()}return}if(action==='clear-message'){state.error='';render();return}if(action==='back'){history.back();return}if(action==='start-block'){state.blockConfirm=id;render();return}if(action==='cancel-block'){state.blockConfirm=null;render();return}if(action==='refresh'){state.busy=true;state.pendingUi={action,startedAt:Date.now()};paintPending();await refreshState();if(currentRoute()==='operations'&&canReadOps())await loadOps();setNotice(t('saved'));render();return}
  state.busy=true;state.pendingUi={action,id,startedAt:Date.now()};render();let actionMap={publish:()=>api('/api/publish','POST',{preview_id:state.preview?.id}), 'request-seat':()=>api('/api/request','POST',{match_id:id}), accept:()=>api('/api/accept','POST',{booking_id:id}), decline:()=>api('/api/decline','POST',{booking_id:id,reason:t('declinedByDriver')}), 'cancel-booking':()=>api('/api/cancel_booking','POST',{booking_id:id,reason:t('cancelledByUser')}), 'board-segment':()=>api('/api/board_segment','POST',{booking_id:id}), 'complete-segment':()=>api('/api/complete_segment','POST',{booking_id:id}), 'start-trip':()=>api('/api/start_trip','POST',{trip_id:id}), 'complete-trip':()=>api('/api/complete_trip','POST',{trip_id:id}), 'cancel-trip':()=>api('/api/cancel_trip','POST',{trip_id:id,reason:t('cancelledByDriver')}), 'confirm-block':()=>api('/api/block_person','POST',{booking_id:id}), 'resolve-report':()=>api('/api/resolve_report','POST',{report_id:id,resolution:resolutionText})};if(actionMap[action]){try{await actionMap[action]()}catch(err){if(![400,401,403,409].includes(err.status)){setNotice(t('retrying'));await refreshState();throw err}throw err}await refreshState();setNotice(t('saved'))}if(action==='confirm-block')state.blockConfirm=null;if(action==='resolve-report')delete state.adminResolutionDrafts[id];if(action==='publish'){state.preview=null;state.form=null;state.formDrafts={};state.routePoints={origin:null,destination:null};state.skipCaptureOnce=true;nav('journeys')}if(action==='request-seat'){state.fareReviewId=null;nav('bookings')}if(currentRoute()==='operations'&&canReadOps())await loadOps();
 }catch(err){if(err.status===401)await expireSession();else setError(err)}finally{state.busy=false;clearPending();render()}}
async function loadBootstrap(){state.boot=await api('/api/bootstrap');state.csrf=state.boot.csrf_token;state.user=state.boot.user}
async function expireSession(){state.logoutPending=false;state.logoutRetrying=false;state.logoutFailed=false;state.logoutAttempt=null;state.sessionSyncing=false;state.sessionSyncFailed=false;resetAccountState();try{await loadBootstrap()}catch{}state.error='Session expired. Sign in again.';state.notice='';}
async function init(){try{await loadBootstrap();if(state.user){await refreshState();const requested=currentRoute(),route=landingIntentRoute(requested);if(route!==requested)nav(route);if(currentRoute()==='operations'&&canReadOps())await loadOps()}}catch(e){setError(e)}render()}
window.addEventListener('hashchange',async()=>{
  state.error='';state.menuOpen=false;const route=currentRoute(),actor=state.user?.id;
  if(route!=='results'&&!state.busy)state.fareReviewId=null;
  if(state.renderedRoute!==route)render();
  if(!state.user)return;
  try{await refreshState();if(currentRoute()!==route)return;if(route==='operations'&&canReadOps())await loadOps();
    const safeView=['inbox','bookings','journeys','operations'].includes(route)||route.startsWith('trip/');
    if(state.user?.id!==actor||safeView)render();
  }catch(e){if(currentRoute()===route){setError(e);render()}}
});
function syncLoadingVisibility(){document.documentElement.dataset.seatpalHidden=String(document.hidden)}
syncLoadingVisibility();
let pollTimer,lastResumeCheckAt=0;
function revalidateOnResume(){if(!state.user||state.logoutPending||state.sessionSyncing)return;const now=Date.now();if(now-lastResumeCheckAt<750)return;lastResumeCheckAt=now;captureDraft();void revalidateSession()}
document.addEventListener('visibilitychange',()=>{syncLoadingVisibility();if(document.hidden){clearInterval(pollTimer)}else{revalidateOnResume();if(state.user)startPolling()}});
window.addEventListener('focus',()=>{if(!document.hidden)revalidateOnResume()});
function startPolling(){clearInterval(pollTimer);pollTimer=setInterval(async()=>{if(!state.user||document.hidden||state.logoutPending||state.sessionSyncing)return;const old=state.user.id;try{const before=JSON.stringify(state.data);const d=await refreshState();const changed=JSON.stringify(state.data)!==before;if(d.user?.id!==old){void revalidateSession({remoteChange:true});return}else{const route=currentRoute();const safeView=route==='inbox'||route==='bookings'||route==='journeys'||route.startsWith('trip/');const active=document.activeElement;const typing=active&&app.contains(active)&&(['INPUT','SELECT','TEXTAREA'].includes(active.tagName)||active.isContentEditable);if(changed&&safeView&&!typing&&!state.busy)render()}}catch(e){if(e.status===401){await expireSession();render()}}},15000)}
document.querySelector('[data-seatpal-startup]')?.setAttribute('data-animate','true');
const startupStatus=document.querySelector('[data-startup-status]');
if(startupStatus)startupStatus.textContent=`${t('name')} · ${t('loading')}`;
const startupLink=document.querySelector('[data-startup-link]');
if(startupLink){
  startupLink.href=`/welcome?lang=${state.lang==='te'?'te':'en'}`;
  startupLink.textContent=state.lang==='te'?'యాప్ గురించి':state.lang==='hi'?'ऐप के बारे में (English)':'About the app';
}
init().then(startPolling);
app.addEventListener('click', async event=>{
  const option=event.target.closest?.('[data-ride-option]');
  if(option){const mode=option.dataset.rideOption;if(!['best','fastest','cheapest','comfort'].includes(mode))return;state.resultsMode=mode;render();document.querySelector(`[data-ride-option="${mode}"]`)?.focus({preventScroll:true});return}
  const action=event.target.closest?.('[data-results-action]')?.dataset.resultsAction;
  if(action==='edit-search'){
    state.form=requestDraftFromSaved(state.results?.request||{});state.formDrafts['search-form']=state.form;state.routePoints={origin:null,destination:null};
    for(const name of ['origin','destination']){const values=state.form.values;if(values[`${name}_label`]&&values[`${name}_lat`]!=='')state.routePoints[name]={label:values[`${name}_label`],lat:Number(values[`${name}_lat`]),lon:Number(values[`${name}_lon`])}}
    nav('search-form');return;
  }
  if(action==='search-again'){
    if(!state.results?.request)return;state.busy=true;state.pendingUi={action,startedAt:Date.now()};render();
    try{const out=await api('/api/search','POST',searchPayload(requestDraftFromSaved(state.results.request).values));state.results={...out,saved_search:true,saved_at:out.saved_at||out.request?.created_at||new Date().toISOString()};state.resultsMode='best';state.error='';setNotice('Search saved.');await refreshState()}
    catch(error){if(error.status===401)await expireSession();else setError(error)}finally{state.busy=false;state.pendingUi=null;render()}
  }
});
app.addEventListener('change',event=>{if(event.target.matches?.('[data-baggage-capacity-toggle]')){const fields=app.querySelector('[data-baggage-capacity-fields]');if(fields){fields.disabled=!event.target.checked;fields.hidden=!event.target.checked}}});
