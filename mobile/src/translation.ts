import {messages} from './generated/i18n';
export function T(lang:string,key:string) { const all=messages as Record<string,Record<string,string>>; const english=all.en; const row=all[lang] || english; return row[key] ?? english[key] ?? key; }
