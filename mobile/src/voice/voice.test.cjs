const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
function load(name) {
  const file = path.join(__dirname, name + '.ts');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText;
  const mod = new Module(file, module); mod.filename = file; mod.paths = module.paths; mod._compile(compiled, file); return mod.exports;
}
const {parseTripTranscript: parse} = load('parser');
const now = new Date('2026-10-06T12:00:00Z');
test('English natural trip retains morning without inventing an hour', () => {
  const draft = parse('Gachibowli to Vijayawada tomorrow morning for two people', now);
  assert.equal(draft.fromQuery, 'Gachibowli'); assert.equal(draft.toQuery, 'Vijayawada');
  assert.equal(draft.date, '2026-10-07'); assert.equal(draft.timePeriod, 'morning'); assert.equal(draft.seats, 2);
  assert.equal(draft.time, undefined); assert.deepEqual(draft.missing, ['time']);
});
test('conversational Telugu and transliteration extract arbitrary places', () => {
  for (const [spoken, from, to] of [
    ['గచ్చిబౌలి నుంచి విజయవాడకి రేపు ఉదయం ఇద్దరికి రైడ్ కావాలి', 'గచ్చిబౌలి', 'విజయవాడ'],
    ['Kondapur nunchi Eluru ki repu udayam iddariki ride kavali', 'Kondapur', 'Eluru'],
  ]) {
    const draft = parse(spoken, now); assert.equal(draft.fromQuery, from); assert.equal(draft.toQuery, to); assert.equal(draft.seats, 2); assert.equal(draft.date, '2026-10-07');
  }
});
test('real Telugu transcript with emphatic dative yields the exact complete trip', () => {
  const draft = parse('గచ్చిబౌలి నుంచి విజయవాడకి రేపు ఉదయం ఎనిమిది గంటలకు ఒక్కరికీ రైడ్ కావాలి', now);
  assert.equal(draft.fromQuery, 'గచ్చిబౌలి'); assert.equal(draft.toQuery, 'విజయవాడ');
  assert.equal(draft.date, '2026-10-07'); assert.equal(draft.time, '08:00'); assert.equal(draft.seats, 1);
  assert.deepEqual(draft.missing, []); assert.deepEqual(draft.ambiguous, []);
});
test('standard Telugu short and emphatic dative person forms preserve their counts', () => {
  for (const [count, forms] of [[1, ['ఒక్కరికి', 'ఒక్కరికీ', 'ఒకరికి', 'ఒకరికీ']], [2, ['ఇద్దరికి', 'ఇద్దరికీ', 'రెండు మందికి', 'రెండు మందికీ']], [3, ['ముగ్గురికి', 'ముగ్గురికీ']]]) {
    for (const form of forms) {
      const draft = parse('ఒంగోలు నుంచి నెల్లూరుకి ' + form + ' రైడ్ కావాలి', now);
      assert.equal(draft.seats, count, form);
      if (!form.startsWith('రెండు')) assert.equal(draft.toQuery, 'నెల్లూరు', form);
    }
  }
});
test('Telugu negated or conflicting dative counts remain ambiguous', () => {
  for (const phrase of ['ఒక్కరికీ కాదు ఇద్దరికీ', 'ఒక్కరికి కాదు', 'ఒకరికీ వద్దు', 'ఇద్దరికీ కాకుండా ఒక్కరికీ', 'ముగ్గురికీ కాదు ఇద్దరికీ', 'రెండు మందికీ కాదు', 'ఒక్కరికీ ఇద్దరికి']) {
    const draft = parse('ఒంగోలు నుంచి నెల్లూరుకి రేపు ' + phrase + ' రైడ్ కావాలి', now);
    assert.equal(draft.seats, undefined, phrase); assert.ok(draft.ambiguous.includes('seats'), phrase);
  }
});
test('sound-alike misspellings and embedded Telugu fragments are not repaired into counts', () => {
  for (const phrase of ['వక్కరికి', 'వక్కరికీ', 'వొక్కడికి', 'నాఒక్కరికీ', 'ఇద్దరికీలాంటి']) {
    const draft = parse('ఒంగోలు నుంచి నెల్లూరుకి రేపు ' + phrase + ' రైడ్ కావాలి', now);
    assert.equal(draft.seats, undefined, phrase); assert.ok(draft.missing.includes('seats'), phrase);
  }
});
test('explicit English and Telugu number-word times resolve only with a period', () => {
  assert.equal(parse('book a ride from Ongole to Nellore tomorrow at eight am for one person', now).time, '08:00');
  assert.equal(parse('ఒంగోలు నుంచి నెల్లూరుకి రేపు సాయంత్రం ఆరు గంటలకు ఒక్కరికి', now).time, '18:00');
  assert.equal(parse('Ongole to Nellore tomorrow at eight for one person', now).time, undefined);
  assert.deepEqual(parse('Ongole to Nellore tomorrow at eight for one person', now).ambiguous, ['time']);
});
test('dates use India calendar even near UTC midnight and explicit dates validate', () => {
  assert.equal(parse('A to B today', new Date('2026-10-06T20:00:00Z')).date, '2026-10-07');
  assert.equal(parse('A to B tomorrow', new Date('2026-12-31T20:00:00Z')).date, '2027-01-02');
  assert.equal(parse('A to B on 2026-10-10 at 14:30', now).date, '2026-10-10');
  assert.equal(parse('A to B on 10 October 2026', now).date, '2026-10-10');
  assert.equal(parse('A to B on 2026-02-30', now).date, undefined);
  assert.equal(parse('A to B on 10/11', now).date, undefined);
  assert.equal(parse('A to B today tomorrow', now).date, undefined);
});
test('conflicting clock times and counts are not silently resolved', () => {
  const clock = parse('A to B tomorrow at 8 am or 9 am for two people', now);
  assert.equal(clock.time, undefined); assert.ok(clock.ambiguous.includes('time'));
  const seats = parse('A to B tomorrow for two people or three people', now);
  assert.equal(seats.seats, undefined); assert.ok(seats.ambiguous.includes('seats'));
  assert.equal(parse('A to B for 12 people', now).seats, 12);
});
test('missing values are explicit and request intent never submits', () => {
  const draft = parse('request a ride', now); assert.equal(draft.intent, 'prepare_booking');
  assert.deepEqual(draft.missing, ['from','to','date','time','seats']);
  assert.equal(parse('book a ride from Little Mount to New Town tomorrow', now).fromQuery, 'Little Mount');
  assert.equal(parse('', now).seats, undefined);
});
test('intent prefixes never become a starting place', () => {
  for (const spoken of [
    'I want to go from Hyderabad to Vijayawada tomorrow at eight am',
    "I'd like to book a ride from Hyderabad to Vijayawada tomorrow",
    'I would like to go Hyderabad to Vijayawada tomorrow',
    'Can you search for a ride from Hyderabad to Vijayawada tomorrow',
  ]) {
    const draft = parse(spoken, now); assert.equal(draft.fromQuery, 'Hyderabad'); assert.equal(draft.toQuery, 'Vijayawada');
  }
});
test('whole clock tokens reject suffix matches and support explicit midnight/24-hour time', () => {
  for (const clock of ['108 am', '28 am', '18 am', '-8 am', 'twenty eight am', '8:99 pm']) {
    assert.equal(parse('A to B tomorrow at ' + clock, now).time, undefined, clock);
  }
  assert.equal(parse('A to B tomorrow at 0:30', now).time, '00:30');
  assert.equal(parse('A to B tomorrow at 12 midnight', now).time, '00:00');
  assert.equal(parse('A to B tomorrow at 12 noon', now).time, '12:00');
  assert.equal(parse('A to B tomorrow at 12', now).time, undefined);
});
test('mixed-language conflicting counts and negative/compound numbers do not become one passenger', () => {
  for (const count of ['two people ముగ్గురికి', 'ఇద్దరికి ఒక్కరికి', '-2 people', 'minus two people', 'twenty two people']) {
    const draft = parse('A to B tomorrow for ' + count, now); assert.equal(draft.seats, undefined, count); assert.ok(draft.ambiguous.includes('seats'), count);
  }
});
test('ride ordinal is a review candidate only', () => {
  assert.equal(parse('book the first ride', now).rideOrdinal, 1);
  assert.equal(parse('రెండో రైడ్ బుక్ చేయండి', now).rideOrdinal, 2);
  assert.equal(parse('First Avenue to Second Street tomorrow', now).rideOrdinal, undefined);
});
test('contradictory periods and invalid counts remain unresolved', () => {
  assert.equal(parse('A to B tomorrow morning at 8 pm', now).time, undefined);
  assert.equal(parse('A to B tomorrow morning evening at 8', now).time, undefined);
  assert.equal(parse('A to B for zero people', now).seats, undefined);
  assert.equal(parse('A to B for 0 people', now).seats, undefined);
});
