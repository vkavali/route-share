import React, {useMemo, useState} from 'react';
import {Modal, Platform, Pressable, StyleSheet,  View} from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import {T} from './translation';
import {Icon} from './Icon';
import {AppText} from './NativeTypography';

const IST = 'Asia/Kolkata';
const IST_OFFSET_MS = 330 * 60 * 1000;
type Stage = 'date' | 'time';

type Props = {
  label: string;
  compact?: boolean;
  value: string;
  onChange: (nextISO: string) => void;
  lang: string;
  minimumDate?: Date;
  maximumDate?: Date;
};

type Parts = {year: number; month: number; day: number; hour: number; minute: number};

function partsInIST(date: Date): Parts {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: IST,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const number = (type: string) => Number(parts.find(part => part.type === type)?.value || 0);
  return {year: number('year'), month: number('month'), day: number('day'), hour: number('hour'), minute: number('minute')};
}

function fromISO(value: string): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return null;
  const p = partsInIST(parsed);
  return new Date(Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - IST_OFFSET_MS);
}

function fromISTParts(parts: Parts): Date {
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute) - IST_OFFSET_MS);
}

function toISO(date: Date): string {
  const p = partsInIST(date);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}T${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}:00+05:30`;
}

function formatValue(value: string, lang: string): string {
  const date = fromISO(value);
  if (!date) return '';
  const locale = lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';
  return new Intl.DateTimeFormat(locale, {dateStyle: 'medium', timeStyle: 'short', timeZone: IST}).format(date);
}

function seedDraft(value: string): Date {
  return fromISO(value) || new Date(Date.now() + 60 * 60 * 1000);
}

/**
 * Native date/time field whose value is always an explicit Asia/Kolkata ISO timestamp.
 * An empty field stays empty until the user confirms both a date and a time.
 */
export function DateTimeField({label, value, onChange, lang, minimumDate, maximumDate, compact = false}: Props) {
  const [stage, setStage] = useState<Stage | null>(null);
  const [draft, setDraft] = useState<Date>(() => seedDraft(value));
  const dateValue = useMemo(() => fromISO(value), [value]);
  const locale = lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';

  const open = () => {
    setDraft(seedDraft(value));
    setStage('date');
  };
  const cancel = () => setStage(null);
  const commit = (next: Date) => {
    onChange(toISO(next));
    setStage(null);
  };
  const handleChange = (event: any, selected?: Date) => {
    if (event?.type !== 'set' || !selected) {
      cancel();
      return;
    }
    if (stage === 'date') {
      const current = partsInIST(draft);
      const picked = partsInIST(selected);
      setDraft(fromISTParts({...current, year: picked.year, month: picked.month, day: picked.day}));
      if (Platform.OS === 'android') setStage('time');
      return;
    }
    const current = partsInIST(draft);
    const picked = partsInIST(selected);
    const next = fromISTParts({...current, hour: picked.hour, minute: picked.minute});
    if (Platform.OS === 'android') commit(next);
    else setDraft(next);
  };

  return <View style={[styles.container,compact&&styles.compactContainer]}>
    <AppText style={[styles.label,compact&&styles.compactLabel]}>{label}</AppText>
    {!compact?<AppText style={styles.zone}>{T(lang, 'timeZoneNote')}</AppText>:null}
    <View style={styles.actions}>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label}, ${dateValue ? formatValue(value, lang) : T(lang, 'dateTimeChoose')}`} onPress={open} style={({pressed}) => [styles.valueButton,compact&&styles.compactValueButton, pressed && styles.pressed]}>
        <>{compact?<Icon name="calendarBlank" size={19} color="#7B8780"/>:null}<AppText style={[styles.valueText,compact&&styles.compactValueText]}>{dateValue ? formatValue(value, lang) : T(lang, 'dateTimeChoose')}{compact?' · IST':''}</AppText></>
      </Pressable>
      {dateValue ? <Pressable accessibilityRole="button" onPress={() => onChange('')} style={styles.clearButton}><AppText style={styles.clearText}>{T(lang, 'dateTimeClear')}</AppText></Pressable> : null}
    </View>
    {Platform.OS === 'android' && stage ? <DateTimePicker
      mode={stage}
      value={draft}
      locale={locale}
      timeZoneName={IST}
      is24Hour
      minimumDate={stage === 'date' ? minimumDate : undefined}
      maximumDate={stage === 'date' ? maximumDate : undefined}
      onChange={handleChange}
    /> : null}
    {Platform.OS === 'ios' ? <Modal visible={stage !== null} transparent animationType="fade" onRequestClose={cancel}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <AppText style={styles.sheetTitle}>{label}</AppText>
          <AppText style={styles.sheetZone}>{T(lang, 'timeZoneNote')}</AppText>
          <View style={styles.stageTabs}>
            <Pressable accessibilityRole="button" onPress={() => setStage('date')} style={[styles.stageTab, stage === 'date' && styles.stageTabActive]}><AppText style={styles.stageTabText}>{T(lang, 'dateTimeDate')}</AppText></Pressable>
            <Pressable accessibilityRole="button" onPress={() => setStage('time')} style={[styles.stageTab, stage === 'time' && styles.stageTabActive]}><AppText style={styles.stageTabText}>{T(lang, 'dateTimeTime')}</AppText></Pressable>
          </View>
          {stage ? <DateTimePicker
            mode={stage}
            display="spinner"
            value={draft}
            locale={locale}
            timeZoneName={IST}
            is24Hour
            minimumDate={stage === 'date' ? minimumDate : undefined}
            maximumDate={stage === 'date' ? maximumDate : undefined}
            onChange={(event: any, selected?: Date) => {
              if (event?.type !== 'set' || !selected) return;
              if (stage === 'date') {
                const current = partsInIST(draft);
                const picked = partsInIST(selected);
                setDraft(fromISTParts({...current, year: picked.year, month: picked.month, day: picked.day}));
              } else {
                const current = partsInIST(draft);
                const picked = partsInIST(selected);
                setDraft(fromISTParts({...current, hour: picked.hour, minute: picked.minute}));
              }
            }}
          /> : null}
          <View style={styles.sheetActions}>
            <Pressable accessibilityRole="button" onPress={cancel} style={styles.cancelButton}><AppText style={styles.cancelText}>{T(lang, 'dateTimeCancel')}</AppText></Pressable>
            {stage === 'date' ? <Pressable accessibilityRole="button" onPress={() => setStage('time')} style={styles.confirmButton}><AppText style={styles.confirmText}>{T(lang, 'dateTimeContinue')}</AppText></Pressable> : <Pressable accessibilityRole="button" onPress={() => commit(draft)} style={styles.confirmButton}><AppText style={styles.confirmText}>{T(lang, 'dateTimeDone')}</AppText></Pressable>}
          </View>
        </View>
      </View>
    </Modal> : null}
  </View>;
}

const styles = StyleSheet.create({
  compactContainer:{marginBottom:0,gap:4,paddingVertical:9,paddingHorizontal:12,borderWidth:1,borderColor:'#E0E3DC',borderRadius:11,backgroundColor:'#FFFFFF'},compactLabel:{fontSize:11,fontWeight:'500',color:'#7B8780'},compactValueButton:{minHeight:34,paddingHorizontal:0,borderWidth:0,flexDirection:'row',alignItems:'center',justifyContent:'flex-start',gap:8},compactValueText:{flex:1,fontSize:13,fontWeight:'500'},
  container: {gap: 7, marginBottom: 13},
  label: {color: '#153C32', fontSize: 15, fontWeight: '700'},
  zone: {color: '#71857B', fontSize: 12},
  actions: {flexDirection: 'row', alignItems: 'center', gap: 10},
  valueButton: {minHeight: 48, flex: 1, justifyContent: 'center', paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: '#DCE4D8', backgroundColor: '#fff'},
  valueText: {color: '#153C32', fontSize: 15, fontWeight: '600'},
  clearButton: {minHeight: 44, justifyContent: 'center', paddingHorizontal: 8},
  clearText: {color: '#71857B', fontSize: 13, fontWeight: '600'},
  pressed: {opacity: .78},
  backdrop: {flex: 1, justifyContent: 'center', padding: 16, backgroundColor: 'rgba(12,30,58,.46)'},
  sheet: {overflow: 'hidden', borderRadius: 20, padding: 18, backgroundColor: '#fff'},
  sheetTitle: {color: '#153C32', fontSize: 18, fontWeight: '800'},
  sheetZone: {color: '#71857B', fontSize: 12, marginTop: 4},
  stageTabs: {flexDirection: 'row', gap: 8, marginTop: 14},
  stageTab: {flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 10, backgroundColor: '#E9EEE6'},
  stageTabActive: {backgroundColor: '#D8ED79'},
  stageTabText: {color: '#153C32', fontWeight: '700'},
  sheetActions: {flexDirection: 'row', justifyContent: 'flex-end', gap: 9, marginTop: 10},
  cancelButton: {minHeight: 46, minWidth: 92, alignItems: 'center', justifyContent: 'center', borderRadius: 11, borderWidth: 1, borderColor: '#DCE4D8'},
  cancelText: {color: '#71857B', fontWeight: '700'},
  confirmButton: {minHeight: 46, minWidth: 112, alignItems: 'center', justifyContent: 'center', borderRadius: 11, paddingHorizontal: 14, backgroundColor: '#153C32'},
  confirmText: {color: '#FFFFFF', fontWeight: '800'},
});
