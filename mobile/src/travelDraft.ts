import type {VoiceTripDraft} from './voice';

/** Only an explicit, unambiguous date AND clock time may prefill the reviewed start. */
export function reviewedVoiceStart(draft:VoiceTripDraft):string {
 if(!draft.date||!draft.time||draft.ambiguous.some(key=>/date|time/i.test(key)))return '';
 if(!/^\d{4}-\d{2}-\d{2}$/.test(draft.date)||!/^\d{2}:\d{2}$/.test(draft.time))return '';
 const [year,month,day]=draft.date.split('-').map(Number),[hour,minute]=draft.time.split(':').map(Number);
 const check=new Date(Date.UTC(year,month-1,day));
 if(check.getUTCFullYear()!==year||check.getUTCMonth()!==month-1||check.getUTCDate()!==day||hour>23||minute>59)return '';
 return `${draft.date}T${draft.time}:00+05:30`;
}
export function prepareVoiceDraft(draft:VoiceTripDraft) {
 return {fromQuery:draft.fromQuery?.trim()||'',toQuery:draft.toQuery?.trim()||'',
  windowStart:reviewedVoiceStart(draft),windowEnd:'',
  seats:typeof draft.seats==='number'?String(draft.seats):''};
}
function explicitTimestamp(value:string):boolean {
 const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value);
 if(!match)return false;
 const [,y,m,d,h,min,sec]=match,check=new Date(Date.UTC(Number(y),Number(m)-1,Number(d)));
 return check.getUTCFullYear()===Number(y)&&check.getUTCMonth()===Number(m)-1&&check.getUTCDate()===Number(d)&&Number(h)<24&&Number(min)<60&&Number(sec||0)<60&&Number.isFinite(Date.parse(value));
}
export function validRideWindow(start:string,end:string,nowMs=Date.now()):boolean {
 if(!explicitTimestamp(start)||!explicitTimestamp(end))return false;
 const first=Date.parse(start),last=Date.parse(end);
 return last>first&&last-first<=12*3600000&&last>nowMs&&first<=nowMs+90*86400000;
}
export function isOrdinalSelection(draft:VoiceTripDraft):boolean {
 return Number.isInteger(draft.rideOrdinal)&&Number(draft.rideOrdinal)>0&&!draft.fromQuery&&!draft.toQuery&&!draft.date&&!draft.time&&!draft.timePeriod&&draft.ambiguous.length===0;
}
export function ordinalMatch<T>(matches:T[],oneBased:number|undefined,complete:boolean):T|null {
 return complete&&Number.isInteger(oneBased)&&Number(oneBased)>0&&Number(oneBased)<=matches.length?matches[Number(oneBased)-1]:null;
}
/** Invalidating on edits makes an old asynchronous response harmless. */
export class SearchGeneration {
 private revision=0;
 private active:number|null=null;
 begin():number|null {if(this.active!==null)return null;this.active=++this.revision;return this.active;}
 invalidate():boolean {const pending=this.active!==null;this.revision++;this.active=null;return pending;}
 current(token:number):boolean{return this.revision===token&&this.active===token;}
 finish(token:number):boolean{if(!this.current(token))return false;this.active=null;return true;}
}
