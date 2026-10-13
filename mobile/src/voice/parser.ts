export type VoiceLanguage = 'en' | 'te' | 'hi';
export type TripField = 'from' | 'to' | 'date' | 'time' | 'seats';
export type VoiceTripDraft = {
  transcript: string;
  intent: 'search' | 'prepare_booking';
  fromQuery?: string;
  toQuery?: string;
  date?: string;
  time?: string;
  timePeriod?: 'morning' | 'afternoon' | 'evening' | 'night';
  seats?: number;
  /** One-based ordinal from a spoken ride choice; still requires visible ride review. */
  rideOrdinal?: number;
  missing: TripField[];
  ambiguous: string[];
};

const numbers: Record<string, number> = {
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12,
  okati: 1, rendu: 2, moodu: 3, nalugu: 4, aidu: 5, aaru: 6, edu: 7, enimidi: 8, tommidi: 9, padi: 10,
  ఒకటి: 1, రెండు: 2, మూడు: 3, నాలుగు: 4, ఐదు: 5, ఆరు: 6, ఏడు: 7, ఎనిమిది: 8, తొమ్మిది: 9, పది: 10, పదకొండు: 11, పన్నెండు: 12,
};
const numberPattern = Object.keys(numbers).sort((a, b) => b.length - a.length).join('|');
const numeric = (text: string) => /^-?\d+$/.test(text) ? Number(text) : numbers[text];
const isoDate = (date: Date) => date.toISOString().slice(0, 10);
function indiaDay(now: Date) { return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours(), now.getUTCMinutes() + 330)); }
const boundary = '(?=\\s|$|[,.;!?])';

/** Extracts candidates only. No geocoding, inferred AM/PM, default seats, or booking side effects. */
export function parseTripTranscript(transcript: string, now = new Date()): VoiceTripDraft {
  const text = transcript.normalize('NFC').replace(/[౦-౯]/g, c => String(c.charCodeAt(0) - 0x0c66)).replace(/\s+/g, ' ').trim();
  const lower = text.toLowerCase();
  const draft: VoiceTripDraft = {transcript, intent: /\b(book|booking|request|reserve)\b|బుక్|బుకింగ్|రిజర్వ్/.test(lower) ? 'prepare_booking' : 'search', missing: [], ambiguous: []};
  const ordinal = lower.match(/(?:\b(first|second|third|fourth|fifth)\s+(?:ride|one|option)\b)|(మొదటి|రెండో|రెండవ|మూడో|మూడవ|నాలుగో|ఐదో)\s*(?:రైడ్|వన్)/);
  if (ordinal) draft.rideOrdinal = ({first: 1, second: 2, third: 3, fourth: 4, fifth: 5, మొదటి: 1, రెండో: 2, రెండవ: 2, మూడో: 3, మూడవ: 3, నాలుగో: 4, ఐదో: 5} as Record<string, number>)[ordinal[1] || ordinal[2]];
  const day = indiaDay(now);
  const tomorrow = /\btomorrow\b|\brepu\b|రేపు/.test(lower);
  const today = /\btoday\b|\bivala\b|\bivvala\b|ఈరోజు|ఇవాళ/.test(lower);
  const dates = [...lower.matchAll(/\b(\d{4})-(\d{2})-(\d{2})\b/g)];
  if ((today && tomorrow) || dates.length > 1 || (dates.length && (today || tomorrow))) draft.ambiguous.push('date');
  else if (today || tomorrow) {
    if (tomorrow) day.setUTCDate(day.getUTCDate() + 1);
    draft.date = isoDate(day);
  } else if (dates.length === 1) {
    const candidate = dates[0][0], parsed = new Date(`${candidate}T00:00:00Z`);
    if (!Number.isNaN(parsed.getTime()) && isoDate(parsed) === candidate) draft.date = candidate;
    else draft.ambiguous.push('date');
  } else {
    const named = lower.match(/\b(?:(\d{1,2})(?:st|nd|rd|th)?\s+(january|february|march|april|may|june|july|august|september|october|november|december)|(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:st|nd|rd|th)?),?\s+(\d{4})\b/);
    if (named) {
      const month = ['january','february','march','april','may','june','july','august','september','october','november','december'].indexOf(named[2] || named[3]);
      const n = Number(named[1] || named[4]), year = Number(named[5]);
      const parsed = new Date(Date.UTC(year, month, n));
      if (parsed.getUTCMonth() === month && parsed.getUTCDate() === n) draft.date = isoDate(parsed);
      else draft.ambiguous.push('date');
    } else if (/\d{1,2}[/-]\d{1,2}|\b(next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b|ఎల్లుండి/.test(lower)) draft.ambiguous.push('date');
  }
  const periods: [NonNullable<VoiceTripDraft['timePeriod']>, RegExp][] = [
    ['morning', /\bmorning\b|\budayam\b|ఉదయం/], ['afternoon', /\bafternoon\b|\bmadhyahnam\b|మధ్యాహ్నం/],
    ['evening', /\bevening\b|\bsayantram\b|\bsaayantram\b|సాయంత్రం/], ['night', /\bnight\b|\bratri\b|\braathri\b|రాత్రి/],
  ];
  const foundPeriods = periods.filter(([, re]) => re.test(lower));
  if (foundPeriods.length === 1) draft.timePeriod = foundPeriods[0][0];
  if (foundPeriods.length > 1) draft.ambiguous.push('time');
  const clock = new RegExp(`(?:^|\\s)(?:(?:at|around)\\s+)?(-?\\d{1,2}|${numberPattern})(?::([0-5]\\d))?\\s*(a\\.?m\\.?|p\\.?m\\.?|midnight|noon|o'clock|o clock|గంటలకు|గంటలకి|gantalu|gantalaku)${boundary}`, 'i');
  const clockCandidates = [...lower.matchAll(new RegExp(clock.source, 'gi'))];
  const plainClock = new RegExp(`\\bat\\s+(-?\\d{1,2}|${numberPattern})(?::([0-5]\\d))?${boundary}`, 'gi');
  const plainCandidates = [...lower.matchAll(plainClock)];
  let clockMatch: RegExpMatchArray | undefined = clockCandidates[0] || plainCandidates[0];
  if (!clockMatch && draft.timePeriod) clockMatch = lower.match(new RegExp(`(?:morning|evening|afternoon|night|udayam|sayantram|saayantram|ratri|ఉదయం|సాయంత్రం|మధ్యాహ్నం|రాత్రి)\\s+(\\d{1,2}|${numberPattern})(?::([0-5]\\d))?${boundary}`, 'i')) || undefined;
  if (clockMatch) {
    let hour = numeric(clockMatch[1]), minute = clockMatch[2] || '00';
    const suffix = (clockMatch[3] || '').replace(/\./g, '');
    const meridiem = suffix === 'am' || suffix === 'pm' ? suffix : undefined;
    if (hour < 0 || hour > 23 || (meridiem && (hour < 1 || hour > 12)) || foundPeriods.length > 1) draft.ambiguous.push('time');
    else if (suffix === 'midnight' || suffix === 'noon') {
      if (hour !== 12 || clockMatch[2] || (draft.timePeriod && draft.timePeriod !== (suffix === 'midnight' ? 'night' : 'afternoon'))) draft.ambiguous.push('time');
      else draft.time = suffix === 'midnight' ? '00:00' : '12:00';
    } else if (meridiem || draft.timePeriod) {
      const pm = meridiem ? meridiem === 'pm' : draft.timePeriod !== 'morning';
      // Periods do not resolve midnight/noon or unusual hours reliably.
      if (!meridiem && (hour === 0 || hour === 12 || (draft.timePeriod === 'night' && hour < 6) || hour > 12)) draft.ambiguous.push('time');
      else if (meridiem && draft.timePeriod && ((meridiem === 'am') !== (draft.timePeriod === 'morning'))) draft.ambiguous.push('time');
      else { hour = hour % 12 + (pm ? 12 : 0); draft.time = `${String(hour).padStart(2, '0')}:${minute}`; }
    } else if ((hour === 0 || hour > 12) && clockMatch[2]) draft.time = `${String(hour).padStart(2, '0')}:${minute}`;
    else draft.ambiguous.push('time');
  }
  if (clockCandidates.length > 1 || plainCandidates.length > 1 || /\b(?:minus|negative|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\s+\w+\s*(?:am|pm)\b/.test(lower)) {delete draft.time; draft.ambiguous.push('time');}
  const seatExpression = new RegExp(`(?:^|\\s)(?:for\\s+)?(-?\\d+|${numberPattern})\\s*(?:people|persons?|passengers?|seats?|members?|మందికీ|మందికి|మంది|సీట్లు|mandi)${boundary}`, 'gi');
  const seatMatches = [...lower.matchAll(seatExpression)];
  const seatCandidates = seatMatches.map(match => numeric(match[1]));
  const isNegatedCount = (match: RegExpMatchArray) => /^\s*(?:కాదు|వద్దు|లేదు|లేరు|కాకుండా)(?=\s|$|[,.;!?])/.test(lower.slice((match.index || 0) + match[0].length));
  let negatedCount = seatMatches.some(isNegatedCount);
  // Short -కి and emphatic -కీ are both grammatical datives. Match whole
  // person-count words; do not repair sound-alike ASR spellings into a count.
  const personalCounts: [RegExp, number][] = [
    [/(?:^|[\s,;:(])(?:ఇద్దరికి|ఇద్దరికీ|ఇద్దరు)(?=\s|$|[,.;!?:)])|\biddariki\b|\biddaru\b/g, 2],
    [/(?:^|[\s,;:(])(?:ఒక్కరికి|ఒక్కరికీ|ఒక్కరు|ఒకరికి|ఒకరికీ|ఒకరు)(?=\s|$|[,.;!?:)])|\bokkariki\b/g, 1],
    [/(?:^|[\s,;:(])(?:ముగ్గురికి|ముగ్గురికీ|ముగ్గురు)(?=\s|$|[,.;!?:)])|\bmugguriki\b/g, 3],
  ];
  for (const [pattern, count] of personalCounts) for (const match of lower.matchAll(pattern)) {
    seatCandidates.push(count);
    negatedCount ||= isNegatedCount(match);
  }
  if (seatCandidates.length === 1 && !negatedCount && Number.isSafeInteger(seatCandidates[0]) && seatCandidates[0] >= 1) draft.seats = seatCandidates[0];
  else if (seatCandidates.length) draft.ambiguous.push('seats');
  if (/\b(?:minus|negative|not|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)\s+\w+\s+(?:people|persons?|seats?|passengers?)\b/.test(lower)) {delete draft.seats; draft.ambiguous.push('seats');}
  // Keep arbitrary place names; extract only around a recognized route separator.
  const prefix = /^(?:(?:please|can you|i want to|i need to|i would like to|i'd like to|i’d like to|i want|i need|find|search|show|book|request|reserve|go|travel|me|for|a|an|ride|rides|trip|నాకు)\s+)+/i;
  const routeText = text.replace(prefix, '');
  // An explicit “from” wins over the “to” inside conversational intent prefixes.
  const route = text.match(/(?:^|\s)from\s+(.+?)\s+to\s+(.+)/i)
    || routeText.match(/(?:^|\s)(.+?)\s+(?:to|nunchi|nunch|నుంచి|నుండి)\s+(.+)/i);
  if (route) {
    const from = route[1].trim();
    const modifier = /\s+(?=(?:today|tomorrow|repu|ivala|ivvala|morning|afternoon|evening|night|udayam|sayantram|saayantram|ratri|at|around|for|on|రేపు|ఈరోజు|ఇవాళ|ఉదయం|సాయంత్రం|మధ్యాహ్నం|రాత్రి|ఇద్దరికి|ఇద్దరికీ|ఒక్కరికి|ఒక్కరికీ|ఒకరికి|ఒకరికీ|ముగ్గురికి|ముగ్గురికీ|రైడ్|బుక్|ride|rides|kavali|kaavali|\d{4}-\d{2}-\d{2})(?:\s|$))/i;
    const to = route[2].split(modifier)[0].replace(/(?:\s+(?:ki|ku)|కి|కు)$/, '').replace(/[,.!?]+$/, '').trim();
    if (from) draft.fromQuery = from;
    if (to) draft.toQuery = to;
  }
  for (const [field, value] of [['from', draft.fromQuery], ['to', draft.toQuery], ['date', draft.date], ['time', draft.time], ['seats', draft.seats]] as const) if (!value) draft.missing.push(field);
  draft.ambiguous = [...new Set(draft.ambiguous)];
  return draft;
}
