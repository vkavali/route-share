type Language = 'en' | 'te' | 'hi';

const messages: Record<Language, Record<string, string>> = {
  en: {
    booking_already_exists: 'You already have a request for this trip. Review or cancel it before requesting a different segment.',
    booking_price_mismatch: 'The payment total must match the fare saved with this booking.',
  },
  te: {
    booking_already_exists: 'ఈ ట్రిప్ కోసం మీకు ఇప్పటికే ఒక అభ్యర్థన ఉంది. వేరే మార్గం అడిగే ముందు దాన్ని పరిశీలించండి లేదా రద్దు చేయండి.',
    booking_price_mismatch: 'చెల్లింపు మొత్తం ఈ బుకింగ్‌లో సేవ్ చేసిన ఛార్జీతో సరిపోవాలి.',
  },
  hi: {
    booking_already_exists: 'इस यात्रा के लिए आपका एक अनुरोध पहले से है। अलग मार्ग माँगने से पहले उसे देखें या रद्द करें।',
    booking_price_mismatch: 'भुगतान की कुल राशि इस बुकिंग में सहेजे गए किराए से मेल खानी चाहिए।',
  },
};

export function nativeErrorMessage(code: unknown, language: string): string | undefined {
  if (typeof code !== 'string') return undefined;
  const locale = (['en', 'te', 'hi'].includes(language) ? language : 'en') as Language;
  const localized = messages[locale];
  return Object.prototype.hasOwnProperty.call(localized, code) ? localized[code] : undefined;
}
