import type {Point} from './api';

export type PlaceCandidate = Point;

export class SelectionIntent {
 private revision=0;
 next():number{return ++this.revision;}
 isCurrent(token:number):boolean{return token===this.revision;}
}

export function normalizePlace(value:unknown):PlaceCandidate|null {
 if(!value||typeof value!=='object')return null;
 const p=value as Record<string,unknown>;
 if(typeof p.lat!=='number'||typeof p.lon!=='number'||!Number.isFinite(p.lat)||!Number.isFinite(p.lon)||Math.abs(p.lat)>90||Math.abs(p.lon)>180)return null;
 if(typeof p.label!=='string'||!p.label.trim())return null;
 const result:PlaceCandidate={lat:p.lat,lon:p.lon,label:p.label.trim().slice(0,120)};
 for(const key of ['id','name','address','kind'] as const){if(typeof p[key]==='string'&&p[key])result[key]=(p[key] as string).slice(0,key==='address'?500:240);}
 if(Array.isArray(p.bbox)&&p.bbox.length===4&&p.bbox.every(n=>typeof n==='number'&&Number.isFinite(n))){
  const [south,north,west,east]=p.bbox;
  if(south>=-90&&north<=90&&south<=north&&west>=-180&&east<=180&&west<=east)result.bbox=[south,north,west,east];
 }
 return result;
}

export function samePlace(a:PlaceCandidate|null,b:PlaceCandidate):boolean {
 return Boolean(a&&a.lat===b.lat&&a.lon===b.lon&&a.label===b.label);
}
