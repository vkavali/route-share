import React, {createContext, useContext, useState} from 'react';
import {Pressable, StyleSheet, Text as NativeText, View} from 'react-native';
import {useFonts} from 'expo-font';
import {T} from './translation';
import {SeatPalLoader} from './SeatPalLoader';
import {revealNativeFrame} from './startupSplash';

const fontAssets = {
  Manrope400: require('../assets/fonts/Manrope-400.ttf'),
  Manrope500: require('../assets/fonts/Manrope-500.ttf'),
  Manrope600: require('../assets/fonts/Manrope-600.ttf'),
  Manrope700: require('../assets/fonts/Manrope-700.ttf'),
  AnekTelugu400: require('../assets/fonts/AnekTelugu-400.ttf'),
  AnekTelugu500: require('../assets/fonts/AnekTelugu-500.ttf'),
  AnekTelugu600: require('../assets/fonts/AnekTelugu-600.ttf'),
  AnekTelugu700: require('../assets/fonts/AnekTelugu-700.ttf'),
};

const LanguageContext = createContext('en');

export function NativeTypographyProvider({lang, children, startupPending=false}: {lang: string; children: React.ReactNode; startupPending?: boolean}) {
  const [attempt, setAttempt] = useState(0);
  return <FontLoader key={attempt} lang={lang} startupPending={startupPending} onRetry={() => setAttempt(value => value + 1)}>{children}</FontLoader>;
}

function FontLoader({lang, children, onRetry, startupPending}: {lang: string; children: React.ReactNode; onRetry: () => void; startupPending: boolean}) {
  const [loaded, error] = useFonts(fontAssets);
  if (error) {
    return <View onLayout={revealNativeFrame} style={styles.failure}>
      <NativeText style={styles.failureText}>{T(lang, 'fontLoadError')}</NativeText>
      <Pressable accessibilityRole="button" onPress={onRetry} style={styles.retry}>
        <NativeText style={styles.retryText}>{T(lang, 'retry')}</NativeText>
      </Pressable>
    </View>;
  }
  if (!loaded || startupPending) {
    return <View onLayout={revealNativeFrame} style={styles.loading}><SeatPalLoader variant="startup" label={T(lang,'loading')}/></View>;
  }
  return <LanguageContext.Provider value={lang}><View onLayout={revealNativeFrame} style={{flex:1}}>{children}</View></LanguageContext.Provider>;
}

export function AppText({style, lang: scriptLang, ...props}: React.ComponentProps<typeof NativeText> & {lang?: string}) {
  const contextLang = useContext(LanguageContext);
  const lang = scriptLang || contextLang;
  const textStyle = StyleSheet.flatten(style) || {};
  const requested = String(textStyle.fontWeight || '500');
  const weight = requested === '500' || requested === '600' || requested === '700'
    ? requested
    : requested === 'bold' || requested === '800' || requested === '900' ? '700' : '400';
  const family = textStyle.fontFamily || `${lang === 'te' ? 'AnekTelugu' : 'Manrope'}${weight}`;
  const teluguLineHeight = lang === 'te'
    ? Math.max(Number(textStyle.lineHeight || 0), Math.ceil(Number(textStyle.fontSize || 16) * 1.5))
    : undefined;

  return <NativeText {...props} style={[style, {fontFamily: family, fontWeight: 'normal', lineHeight: teluguLineHeight || textStyle.lineHeight, letterSpacing: lang === 'te' ? 0 : textStyle.letterSpacing}]} />;
}

const styles = StyleSheet.create({
  loading: {flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#F6F5F0'},
  failure: {flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24, backgroundColor: '#F6F5F0'},
  failureText: {maxWidth: 330, textAlign: 'center', color: '#153C32', fontSize: 16, lineHeight: 25},
  retry: {minHeight: 46, justifyContent: 'center', paddingHorizontal: 20, borderRadius: 14, backgroundColor: '#153C32'},
  retryText: {color: '#fff', fontSize: 15, fontWeight: '700'},
});
