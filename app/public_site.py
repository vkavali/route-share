"""Anonymous, bilingual product guidance; no account state or provider calls."""
from copy import deepcopy
import re


COPY = {
    'en': {
        'tagline': 'Going the same way?', 'nav_home': 'Home', 'nav_faq': 'FAQs', 'nav_app': 'Open the app',
        'language_label': 'Language',
        'hero': {'eyebrow': 'Hyderabad ↔ Mahabubnagar', 'title': 'Same route? Share the ride.',
                 'body': 'Find a seat with a private car owner already planning the same journey, or offer spare seats on your own trip. Share agreed trip costs, with the details clear before you go.',
                 'cta': 'Open the app'},
        'availability': {'title': 'What is available now'},
        'steps_title': 'From a plan to a shared ride',
        'steps': [
            {'title': 'Find a matching trip', 'body': 'Choose your pickup, drop-off and time window. Results depend on the route, available seats and the owner’s plan.'},
            {'title': 'Request a seat', 'body': 'Review the trip and send a request. Your seat is pending until the owner accepts it.'},
            {'title': 'Agree, then travel', 'body': 'Check the meeting points and any agreed contribution. Use the accepted trip to coordinate with the other participant.'},
        ],
        'facts_title': 'Clear expectations, before you leave',
        'facts': [
            {'title': 'A trip already planned', 'body': 'Share costs on a car journey the owner already planned. A seat depends on someone offering a matching trip; it is not an on-demand taxi.'},
            {'title': 'You choose what to share', 'body': 'Choose whether to share your location with the people in your accepted trip while the app is open. You can stop sharing.'},
            {'title': 'Review the details yourself', 'body': 'Document review and completed-trip ratings provide context. They cannot guarantee anyone’s safety.'},
        ],
        'faq_title': 'Before you share a ride', 'faq_intro': 'How requests, contributions and your information work. You can read these answers without signing in.',
        'support_title': 'Need help?', 'support_body': 'For trip questions, use chat in your accepted booking. For account or safety help, contact us by email. This is not an emergency service.',
        'support_unavailable': 'A public support email is not available yet.',
        'terms_label': 'Terms', 'privacy_label': 'Privacy',
        'footer_note': 'Beta availability can change. Check the app before making travel arrangements.',
        'faq_groups': [
            {'id': 'getting-started', 'title': 'Getting started', 'items': [
                {'question': 'Who is this for?', 'answer': 'Adults sharing a private, already planned car journey between Hyderabad and Mahabubnagar. An owner offers spare seats; a passenger looks for a compatible route and time.'},
                {'question': 'Can I sign up now?', 'answer': ''},
                {'question': 'What if I cannot find a ride?', 'answer': 'No result means no matching trip was found for those details. Review the places and time window, or try again later. A search does not reserve a seat or guarantee a ride.'},
            ]},
            {'id': 'requests', 'title': 'Requests and meeting points', 'items': [
                {'question': 'Is my seat confirmed when I request it?', 'answer': 'No. A request stays pending until the owner accepts it. Read the current trip status and agreed meeting points before leaving.'},
                {'question': 'Can I use the map as navigation?', 'answer': 'The map helps you check the road route and meeting points when they are available. Routes and times are estimates and may change. Use a navigation app for turn-by-turn directions and check current road conditions.'},
                {'question': 'What happens if the app is slow or shows an error?', 'answer': 'Wait for a clear result, then check the trip’s current status before retrying an action. An error or a pending request is not an acceptance or payment confirmation.'},
            ]},
            {'id': 'contributions', 'title': 'Contributions and payments', 'items': [
                {'question': 'Can I pay through the app?', 'answer': ''},
                {'question': 'Does opening UPI prove I paid?', 'answer': 'No. Opening a UPI app is only a handoff. The passenger reports a payment and the owner confirms receipt manually. The app does not verify bank settlement.'},
                {'question': 'How are disputes and refunds handled?', 'answer': 'Participants use the payment record to report a dispute or request and confirm a refund. These steps are manual records: they do not move money or automatically issue a refund. Keep your own payment receipt.'},
            ]},
            {'id': 'trust', 'title': 'Documents and reviews', 'items': [
                {'question': 'What does “Documents reviewed” mean?', 'answer': 'An authorised reviewer has checked the submitted documents recorded in the app, subject to their current expiry and approval status. It is not government or police clearance, a guarantee of identity, or a safety guarantee.'},
                {'question': 'Who can leave a rating?', 'answer': 'Participants can rate a booking after both the trip and their segment are completed. Public review comments require the author’s explicit consent. A rating average is shown only after at least three eligible ratings.'},
            ]},
            {'id': 'location-voice', 'title': 'Location and voice', 'items': [
                {'question': 'Is my location shared all the time?', 'answer': 'No. You choose to share and allow location access. It works while the app is open, only with participants in your accepted trip. You can stop it in the trip. Permission, network or an old location reading can interrupt updates.'},
                {'question': 'Can I enter a trip by speaking?', 'answer': 'When voice is available, you can speak in English or Telugu. Your recording is sent temporarily to this app’s server to turn it into text, then deleted after processing or cancellation. Check and correct the details before searching or sending a request. You can always type instead.'},
            ]},
            {'id': 'account', 'title': 'Your account and information', 'items': [
                {'question': 'Can I delete my account?', 'answer': 'Eligible phone members can request deletion in the app after confirming their phone. Active rides, pending or accepted participation and unresolved payments must be resolved first. Deletion removes current personal data, but minimal historical booking/payment records and restricted safety/audit records remain; backups and provider records have separate retention.'},
                {'question': 'What if I lose access to my phone number?', 'answer': 'Optional recovery requires a recovery code you saved beforehand and verification of a new phone number. If you lose both proofs, there is no promised support bypass. Ordinary sign-in uses phone OTP; the recovery code does not protect against another person receiving OTPs for a recycled number.'},
            ]},
        ],
    },
    'te': {
        'tagline': 'మీ దారీ అదేనా?', 'nav_home': 'హోమ్', 'nav_faq': 'సందేహాలు', 'nav_app': 'యాప్ తెరవండి',
        'language_label': 'భాష',
        'hero': {'eyebrow': 'హైదరాబాద్ ↔ మహబూబ్‌నగర్', 'title': 'ఒకే దారినా? కలిసి వెళ్దాం.',
                 'body': 'మీ దారిలోనే వెళ్లాలని ప్లాన్ చేసుకున్న కారు యజమానితో సీటు పంచుకోండి. లేదా మీ ప్రయాణంలో ఖాళీ సీట్లు ఇవ్వండి. బయలుదేరే ముందే వివరాలు చూసుకుని, ఒప్పుకున్న ప్రయాణ ఖర్చు పంచుకోండి.',
                 'cta': 'యాప్ తెరవండి'},
        'availability': {'title': 'ఇప్పుడు అందుబాటులో ఉన్నవి'},
        'steps_title': 'ప్లాన్ నుంచి ప్రయాణం వరకు',
        'steps': [
            {'title': 'సరిపోయే ట్రిప్ చూడండి', 'body': 'ఎక్కడ ఎక్కాలి, ఎక్కడ దిగాలి, ఏ సమయంలో వెళ్లాలో ఎంచుకోండి. దారి, ఖాళీ సీట్లు, యజమాని ప్లాన్ బట్టి ట్రిప్‌లు కనిపిస్తాయి.'},
            {'title': 'సీటు కోసం అడగండి', 'body': 'వివరాలు చూసి రిక్వెస్ట్ పంపండి. యజమాని అంగీకరించే వరకు సీటు ఖరారు కాదు.'},
            {'title': 'ఒప్పుకున్నాక ప్రయాణించండి', 'body': 'కలిసే చోటు, పంచుకునే ఖర్చు చూసుకోండి. అంగీకరించిన ట్రిప్‌లో అవతలి వ్యక్తితో వివరాలు మాట్లాడుకోండి.'},
        ],
        'facts_title': 'బయలుదేరే ముందే స్పష్టత',
        'facts': [
            {'title': 'ముందే ప్లాన్ చేసిన ప్రయాణం', 'body': 'ఇది ప్రైవేట్ కారు ప్రయాణంలో ఖర్చు పంచుకోవడం. వెంటనే వచ్చే ట్యాక్సీ సర్వీస్ కాదు; రైడ్ దొరుకుతుందనే హామీ లేదు.'},
            {'title': 'ఏం పంచుకోవాలో మీ ఇష్టం', 'body': 'అంగీకరించిన ట్రిప్‌లో ఉన్నవారితో మాత్రమే, యాప్ తెరిచి ఉన్నప్పుడు మీ లొకేషన్ పంచుకోవచ్చు. ఎప్పుడైనా ఆపవచ్చు.'},
            {'title': 'వివరాలు మీరూ చూసుకోండి', 'body': 'డాక్యుమెంట్ సమీక్ష, పూర్తయిన ట్రిప్‌ల రేటింగ్‌లు కొంత సమాచారం ఇస్తాయి. ఎవరి భద్రతకూ అవి హామీ కావు.'},
        ],
        'faq_title': 'ప్రయాణానికి ముందు మీ సందేహాలు', 'faq_intro': 'రిక్వెస్ట్‌లు, ఖర్చు, మీ సమాచారం గురించి తెలుసుకోండి. ఇవి చదవడానికి సైన్ ఇన్ అవసరం లేదు.',
        'support_title': 'సహాయం కావాలా?', 'support_body': 'ట్రిప్ వివరాలకు అంగీకరించిన బుకింగ్‌లో చాట్ వాడండి. అకౌంట్ లేదా భద్రత విషయంలో సహాయం కోసం ఈమెయిల్ చేయండి. ఇది అత్యవసర సహాయ సర్వీస్ కాదు.',
        'support_unavailable': 'సపోర్ట్ ఈమెయిల్ ఇంకా అందుబాటులో లేదు.',
        'terms_label': 'నిబంధనలు', 'privacy_label': 'గోప్యత',
        'footer_note': 'బీటాలో సౌకర్యాలు మారవచ్చు. ప్రయాణం ప్లాన్ చేసే ముందు యాప్‌లో చూసుకోండి.',
        'faq_groups': [
            {'id': 'getting-started', 'title': 'మొదలుపెట్టడం', 'items': [
                {'question': 'ఇది ఎవరి కోసం?', 'answer': 'హైదరాబాద్–మహబూబ్‌నగర్ మధ్య ముందే ప్లాన్ చేసిన ప్రైవేట్ కారు ప్రయాణాన్ని పంచుకునే పెద్దల కోసం. యజమాని ఖాళీ సీట్లు ఇస్తారు; ప్రయాణికుడు తన దారి, సమయానికి సరిపోయే ట్రిప్ చూస్తారు.'},
                {'question': 'ఇప్పుడు కొత్త అకౌంట్ చేసుకోవచ్చా?', 'answer': ''},
                {'question': 'ట్రిప్ దొరక్కపోతే?', 'answer': 'మీ వివరాలకు సరిపోయే ట్రిప్ దొరకలేదని అర్థం. ఎక్కే, దిగే చోటు, సమయం సరిచూడండి లేదా తర్వాత మళ్లీ చూడండి. వెతికినంత మాత్రాన సీటు రిజర్వ్ కాదు; ట్రిప్ దొరుకుతుందనే హామీ లేదు.'},
            ]},
            {'id': 'requests', 'title': 'రిక్వెస్ట్‌లు, కలిసే చోటు', 'items': [
                {'question': 'రిక్వెస్ట్ పంపగానే సీటు ఖరారు అవుతుందా?', 'answer': 'కాదు. యజమాని అంగీకరించే వరకు పెండింగ్‌లో ఉంటుంది. బయలుదేరే ముందు ట్రిప్ స్థితి, ఒప్పుకున్న కలిసే చోటు చూసుకోండి.'},
                {'question': 'మ్యాప్‌ను నావిగేషన్ కోసం వాడొచ్చా?', 'answer': 'దారి, కలిసే చోటు చూసుకోవడానికి మ్యాప్ ఉపయోగపడుతుంది. దారి, సమయం అంచనాలు మాత్రమే; మారవచ్చు. మలుపుల వారీ సూచనలకు నావిగేషన్ యాప్ వాడండి. ఇప్పటి రోడ్డు పరిస్థితులు చూసుకోండి.'},
                {'question': 'యాప్ నెమ్మదిగా ఉంటే లేదా ఎర్రర్ వస్తే?', 'answer': 'స్పష్టమైన ఫలితం వచ్చే వరకు వేచి ఉండండి. మళ్లీ చేసే ముందు ట్రిప్ ఇప్పటి స్థితి చూసుకోండి. ఎర్రర్ లేదా పెండింగ్ రిక్వెస్ట్ అంటే అంగీకారం గానీ, పేమెంట్ నిర్ధారణ గానీ కాదు.'},
            ]},
            {'id': 'contributions', 'title': 'ఖర్చు, పేమెంట్', 'items': [
                {'question': 'యాప్ ద్వారా డబ్బు చెల్లించవచ్చా?', 'answer': ''},
                {'question': 'UPI తెరిస్తే డబ్బు చెల్లించినట్టేనా?', 'answer': 'కాదు. UPI యాప్ తెరవడం ఒక లింక్ మాత్రమే. ప్రయాణికుడు చెల్లించానని నమోదు చేస్తారు; డబ్బు అందిందని యజమాని స్వయంగా నిర్ధారిస్తారు. బ్యాంకులో డబ్బు చేరిందో ఈ యాప్ నిర్ధారించదు.'},
                {'question': 'వివాదం లేదా రీఫండ్ ఉంటే?', 'answer': 'పేమెంట్ రికార్డులో వివాదం చెప్పవచ్చు, రీఫండ్ అడగవచ్చు, తిరిగి ఇచ్చిన డబ్బును నిర్ధారించవచ్చు. ఇవి వ్యక్తులు నమోదు చేసే వివరాలు మాత్రమే. యాప్ డబ్బు పంపదు, ఆటోమేటిక్‌గా రీఫండ్ చేయదు. మీ పేమెంట్ రసీదు దాచుకోండి.'},
            ]},
            {'id': 'trust', 'title': 'డాక్యుమెంట్లు, రేటింగ్‌లు', 'items': [
                {'question': '“డాక్యుమెంట్లు సమీక్షించారు” అంటే?', 'answer': 'అధికారం ఉన్న సమీక్షకుడు యాప్‌లో సమర్పించిన డాక్యుమెంట్లను చూశారని అర్థం. వాటి గడువు, ఇప్పటి ఆమోద స్థితి వర్తిస్తాయి. ఇది ప్రభుత్వ లేదా పోలీసు క్లియరెన్స్ కాదు; వ్యక్తి గుర్తింపు లేదా భద్రతకు హామీ కాదు.'},
                {'question': 'ఎవరు రేటింగ్ ఇవ్వవచ్చు?', 'answer': 'ట్రిప్, తమ ప్రయాణ భాగం రెండూ పూర్తయిన తర్వాత ఆ బుకింగ్‌లో ఉన్నవారు రేటింగ్ ఇవ్వవచ్చు. రాసిన వ్యక్తి స్పష్టంగా ఒప్పుకుంటేనే కామెంట్ పబ్లిక్‌గా కనిపిస్తుంది. కనీసం మూడు అర్హమైన రేటింగ్‌ల తర్వాతే సగటు చూపిస్తాం.'},
            ]},
            {'id': 'location-voice', 'title': 'లొకేషన్, వాయిస్', 'items': [
                {'question': 'నా లొకేషన్ ఎప్పుడూ షేర్ అవుతుందా?', 'answer': 'కాదు. మీరు ఎంచుకుని అనుమతి ఇవ్వాలి. యాప్ ముందువైపు తెరిచి ఉన్నప్పుడు మాత్రమే, అర్హమైన అంగీకరించిన ట్రిప్‌లో ఉన్నవారితో పంచుకుంటుంది. ట్రిప్‌లో షేరింగ్ ఆపవచ్చు. ఫోన్ అనుమతి, నెట్‌వర్క్ లేదా పాత రీడింగ్‌ల వల్ల అప్‌డేట్‌లు ఆగవచ్చు.'},
                {'question': 'మాట్లాడి ట్రిప్ వివరాలు ఇవ్వవచ్చా?', 'answer': 'వాయిస్ అందుబాటులో ఉంటే ఇంగ్లీష్ లేదా తెలుగులో చెప్పవచ్చు. మాటలను టెక్స్ట్‌గా మార్చడానికి రికార్డింగ్ తాత్కాలికంగా ఈ యాప్ సర్వర్‌కు వెళ్తుంది. పని పూర్తయినా, మీరు రద్దు చేసినా అది తొలగుతుంది. వెతికే ముందు, రిక్వెస్ట్ పంపే ముందు వివరాలు చూసి సరిచేయండి. టైప్ చేయవచ్చు కూడా.'},
            ]},
            {'id': 'account', 'title': 'మీ అకౌంట్, సమాచారం', 'items': [
                {'question': 'నా అకౌంట్ తొలగించవచ్చా?', 'answer': 'అర్హమైన ఫోన్ అకౌంట్ సభ్యులు ఫోన్ నిర్ధారించిన తర్వాత యాప్‌లో తొలగింపు కోరవచ్చు. నడుస్తున్న ట్రిప్‌లు, పెండింగ్ లేదా అంగీకరించిన బుకింగ్‌లు, పరిష్కారం కాని పేమెంట్‌లు ముందు ముగించాలి. ఇప్పటి వ్యక్తిగత సమాచారం తొలగుతుంది; అవసరమైన పాత బుకింగ్, పేమెంట్ రికార్డులు, పరిమిత ప్రవేశం ఉన్న భద్రత, ఆడిట్ రికార్డులు ఉంటాయి. బ్యాకప్‌లు, సర్వీస్ ప్రొవైడర్ రికార్డులకు వేరే నిల్వ విధానం ఉంటుంది.'},
                {'question': 'నా ఫోన్ నంబర్ పోతే?', 'answer': 'మీరు ముందే దాచుకున్న రికవరీ కోడ్, కొత్త ఫోన్ నంబర్ నిర్ధారణతో ఐచ్ఛిక రికవరీ చేయవచ్చు. రెండూ లేకపోతే సపోర్ట్ ద్వారా తప్పక తిరిగి వస్తుందనే హామీ లేదు. సాధారణ సైన్ ఇన్ ఫోన్ OTPతోనే ఉంటుంది. పాత నంబర్ మరొకరికి ఇచ్చి, వారికి OTPలు వస్తే రికవరీ కోడ్ ఆ ప్రవేశాన్ని ఆపదు.'},
            ]},
        ],
    },
}


COPY['en']['faq_groups'][0]['items'].append({
    'question': 'How do I offer seats?',
    'answer': 'Complete your profile and apply for document review with your driving licence, vehicle registration, insurance and a selfie. Once approved, publish the journey you already planned with its route, departure and spare seats. Keep documents current; you choose which requests to accept.'})
COPY['te']['faq_groups'][0]['items'].append({
    'question': 'నా కారులో సీట్లు ఎలా ఇవ్వాలి?',
    'answer': 'ప్రొఫైల్ పూర్తి చేసి డ్రైవింగ్ లైసెన్స్, కారు RC, ఇన్సూరెన్స్, సెల్ఫీతో డాక్యుమెంట్ సమీక్షకు దరఖాస్తు చేయండి. ఆమోదం వచ్చాక ముందే ప్లాన్ చేసిన దారి, బయలుదేరే సమయం, ఖాళీ సీట్లతో ట్రిప్ పెట్టండి. డాక్యుమెంట్ల గడువు చూసుకోండి. ఏ రిక్వెస్ట్ అంగీకరించాలో మీ ఇష్టం.'})
COPY['en']['faq_groups'][1]['items'].append({
    'question': 'Can I cancel a request or trip?',
    'answer': 'Open the booking or trip and use Cancel when that action is available. Check that its status changes and tell the other participant about changed plans. Cancellation does not automatically refund money; resolve any recorded contribution separately.'})
COPY['te']['faq_groups'][1]['items'].append({
    'question': 'రిక్వెస్ట్ లేదా ట్రిప్ రద్దు చేయవచ్చా?',
    'answer': 'బుకింగ్ లేదా ట్రిప్ తెరిచి రద్దు చేసే బటన్ అందుబాటులో ఉంటే వాడండి. స్థితి మారిందో చూసి, ప్లాన్ మారిందని అవతలి వ్యక్తికి చెప్పండి. రద్దు చేస్తే డబ్బు ఆటోమేటిక్‌గా తిరిగి రాదు. పేమెంట్ విషయం విడిగా పరిష్కరించుకోండి.'})
COPY['en']['faq_groups'][2]['items'].append({
    'question': 'How is my contribution agreed?',
    'answer': 'The owner declares fuel and toll costs and their own share. The total proposed passenger contributions are capped by the remaining declared costs. Review your own amount before agreeing; the app does not promise a fixed fare or independently verify the declared expenses.'})
COPY['te']['faq_groups'][2]['items'].append({
    'question': 'నేను పంచుకునే ఖర్చు ఎలా నిర్ణయిస్తారు?',
    'answer': 'యజమాని ఇంధనం, టోల్ ఖర్చులు, తమ వాటా చెబుతారు. ప్రయాణికులందరికీ ప్రతిపాదించే మొత్తం, మిగిలిన ప్రకటించిన ఖర్చును మించకూడదు. ఒప్పుకునే ముందు మీ మొత్తం చూసుకోండి. యాప్ నిర్ణీత ధరకు హామీ ఇవ్వదు; చెప్పిన ఖర్చులను స్వయంగా నిర్ధారించదు.'})
COPY['en']['faq_groups'][3]['items'].extend([
    {'question': 'What should I check before getting in?', 'answer': 'Compare the person, vehicle and trip details with what the app shows. Confirm the meeting point and contribution. If anything does not match or you feel uncomfortable, do not start the ride.'},
    {'question': 'How do I report a problem or block someone?', 'answer': 'Use the report and block actions in the app for the relevant person or booking. Describe the issue clearly. Blocking limits future interaction but does not settle a payment or replace emergency assistance. For immediate danger, seek local emergency help.'},
])
COPY['te']['faq_groups'][3]['items'].extend([
    {'question': 'కారులో ఎక్కే ముందు ఏం చూసుకోవాలి?', 'answer': 'వ్యక్తి, కారు, ట్రిప్ వివరాలు యాప్‌లో ఉన్న వాటితో సరిపోల్చండి. కలిసే చోటు, పంచుకునే ఖర్చు నిర్ధారించుకోండి. ఏదైనా తేడాగా లేదా ఇబ్బందిగా అనిపిస్తే ప్రయాణం మొదలుపెట్టకండి.'},
    {'question': 'సమస్య చెప్పడం, బ్లాక్ చేయడం ఎలా?', 'answer': 'సంబంధిత వ్యక్తి లేదా బుకింగ్ కోసం యాప్‌లో రిపోర్ట్, బ్లాక్ వాడండి. సమస్య స్పష్టంగా రాయండి. బ్లాక్ చేస్తే తర్వాతి పరస్పర చర్యలు పరిమితం అవుతాయి; పేమెంట్ సమస్య పరిష్కారం కాదు, అత్యవసర సహాయానికి బదులు కాదు. వెంటనే ప్రమాదం ఉంటే స్థానిక అత్యవసర సహాయం తీసుకోండి.'},
])


COPY['en'].update(owner_steps_title='Offering seats on your own trip?', owner_steps=[
    {'title': 'Apply for document review', 'body': 'Submit the required documents and wait for review. You can offer trips only while your approval and documents remain valid.'},
    {'title': 'Publish the trip you already planned', 'body': 'Enter your route, departure and spare seats. If contributions are available, declare the trip costs and your own share before proposing a contribution.'},
    {'title': 'Review each request', 'body': 'Check the passenger’s meeting points before accepting. Coordinate through the accepted trip and confirm any money received yourself.'},
])
COPY['te'].update(owner_steps_title='మీ ప్రయాణంలో సీట్లు ఇస్తున్నారా?', owner_steps=[
    {'title': 'డాక్యుమెంట్ సమీక్షకు దరఖాస్తు చేయండి', 'body': 'అవసరమైన డాక్యుమెంట్లు పంపి సమీక్ష కోసం వేచి ఉండండి. ఆమోదం, డాక్యుమెంట్ల గడువు చెల్లుబాటులో ఉన్నప్పుడే ట్రిప్‌లు ఇవ్వవచ్చు.'},
    {'title': 'ముందే ప్లాన్ చేసిన ట్రిప్ పెట్టండి', 'body': 'దారి, బయలుదేరే సమయం, ఖాళీ సీట్లు ఇవ్వండి. ఖర్చు పంచుకునే సౌకర్యం ఉంటే, మొత్తం ప్రయాణ ఖర్చు, మీ వాటా తెలిపిన తర్వాతే ప్రయాణికుడి వాటా ప్రతిపాదించండి.'},
    {'title': 'ప్రతి రిక్వెస్ట్ చూసుకోండి', 'body': 'అంగీకరించే ముందు ప్రయాణికుడు ఎక్కే, దిగే చోటు చూడండి. అంగీకరించిన ట్రిప్‌లో మాట్లాడుకోండి. డబ్బు అందితే మీరే నిర్ధారించండి.'},
])


COPY['en'].update(faq_search_label='Search questions', faq_search_placeholder='Try payments, location or account',
                  faq_reset='Clear search', faq_no_results='No matching questions. Try another word or clear the search.',
                  faq_result_count='{count} questions found', skip_content='Skip to content',
                  terms_label='Terms (English)', privacy_label='Privacy (English)')
COPY['te'].update(faq_search_label='ప్రశ్నలు వెతకండి', faq_search_placeholder='పేమెంట్, లొకేషన్ లేదా అకౌంట్',
                  faq_reset='క్లియర్ చేయండి', faq_no_results='సరిపోయే ప్రశ్నలు లేవు. మరో పదంతో వెతకండి లేదా వెతికిన పదం తీసేయండి.',
                  faq_result_count='{count} ప్రశ్నలు దొరికాయి', skip_content='విషయానికి వెళ్లండి',
                  terms_label='నిబంధనలు (ఇంగ్లీష్)', privacy_label='గోప్యత (ఇంగ్లీష్)')


COPY['en'].update(
    role_switch_label='Choose how you travel', role_rider='I need a seat',
    role_owner='I have spare seats', journey_steps_title='Find a seat. Or share yours.',
    faq_categories_label='Browse by topic', steps_title='How it works')
COPY['te'].update(
    role_switch_label='మీకు ఏది కావాలి?', role_rider='సీటు కావాలి',
    role_owner='సీట్లు షేర్ చేస్తాను', journey_steps_title='సీటు వెతకండి. లేదా షేర్ చేయండి.',
    faq_categories_label='విషయం ఎంచుకోండి', steps_title='ఎలా వాడాలి?')

COPY['en']['hero']['body'] = 'Find a seat on someone’s planned journey. Or share the spare seats in yours. Agree the details, share the trip costs, and go together.'
COPY['te']['hero']['body'] = 'మీ దారిలో వెళ్లే ట్రిప్‌లో సీటు చూసుకోండి. లేదా మీ కారులో ఖాళీ సీట్లు షేర్ చేయండి. వివరాలు మాట్లాడుకుని, ఖర్చు పంచుకుని, కలిసి వెళ్లండి.'
COPY['en']['layered'] = {
    'corridor_label': 'Our first corridor', 'origin': 'Hyderabad',
    'destination': 'Mahabubnagar',
    'corridor_note': 'A pilot for private owners and people going the same way. Check the app for matching trips.',
    'story_title': 'One journey. Two ways to join.',
    'story_body': 'Looking for a seat or already taking your car? Start with the journey you actually want to make.',
    'rider_heading': 'Your next seat starts here.',
    'owner_heading': 'Make room for someone going your way.',
    'faq_heading': 'A few things before you go.', 'faq_link': 'Explore all FAQs',
    'final_title': 'Your route could be someone else’s, too.',
    'final_body': 'Open the app to explore the beta. A seat request is confirmed only when the owner accepts.',
}
COPY['te']['layered'] = {
    'corridor_label': 'మొదట ఈ రూట్‌లో', 'origin': 'హైదరాబాద్',
    'destination': 'మహబూబ్‌నగర్',
    'corridor_note': 'ఒకే దారిలో వెళ్లే వారి కోసం ఈ పైలట్. మీకు సరిపోయే ట్రిప్ యాప్‌లో చూడండి.',
    'story_title': 'ఒకే దారి. కలిసి వెళ్దాం.',
    'story_body': 'సీటు కావాలా? మీ కారులో చోటుందా? మీరు వెళ్లాలనుకున్న ట్రిప్‌తో మొదలుపెట్టండి.',
    'rider_heading': 'మీకు సీటు కావాలంటే…',
    'owner_heading': 'మీ దారిలో వెళ్లేవారికి సీటు ఇవ్వండి.',
    'faq_heading': 'వెళ్లే ముందు కొన్ని విషయాలు.', 'faq_link': 'అన్ని సందేహాలు చూడండి',
    'final_title': 'మీ దారిలో ఇంకొకరూ వెళ్తుండొచ్చు.',
    'final_body': 'బీటా చూడటానికి యాప్ తెరవండి. యజమాని అంగీకరించాకే మీ సీటు కన్ఫర్మ్ అవుతుంది.',
}


COPY['en']['local_motion'] = {'pause': 'Pause animation', 'play': 'Play animation'}
COPY['te']['local_motion'] = {'pause': 'యానిమేషన్ ఆపండి', 'play': 'యానిమేషన్ ప్లే చేయండి'}


COPY['en']['journey'] = {
    'eyebrow': 'From your first plan to your next ride',
    'title': 'One route. Every step explained.',
    'body': 'From finding a seat to getting there together—explore each part of the ride.',
    'progress_label': 'Explore the app',
    'stops': [
        {'id': 'plan', 'title': 'Start with your route', 'body': 'Choose your pickup, drop-off and time window to find compatible trips.',
         'details': ['Map points and road estimates help you review the journey; a search does not reserve a seat.', 'Voice input is being tested in the native app. On the web, type your pickup and destination.'], 'faq_anchor': 'location-voice'},
        {'id': 'offer', 'title': 'Share seats on your planned drive', 'body': 'Owners enter their route, departure and spare seats for a journey they already intend to make.',
         'details': ['Offering trips requires current document approval.', 'You choose which requests to accept; this is not an on-demand taxi service.'], 'faq_anchor': 'getting-started'},
        {'id': 'driver', 'title': 'Driver profiles', 'body': 'Review the owner’s profile, vehicle, document-review status and eligible completed-trip ratings.',
         'details': ['Owners submit their licence, RC, insurance and selfie for review.', '“Documents reviewed” is not police clearance or a safety guarantee.'], 'faq_anchor': 'trust'},
        {'id': 'request', 'title': 'Request, then wait for acceptance', 'body': 'Check the meeting points and request a seat; the owner must accept before it is confirmed.',
         'details': ['My trips shows the current booking status.', 'Cancel only through an available action and check the result; cancellation does not refund money automatically.'], 'faq_anchor': 'requests'},
        {'id': 'chat', 'title': 'Agree the meeting details', 'body': 'Use chat in your accepted booking to coordinate with the other participant.',
         'details': ['Confirm the pickup and tell each other if plans change.'], 'faq_anchor': 'requests'},
        {'id': 'live', 'title': 'Share location when you choose', 'body': 'Start optional location sharing with your accepted-trip participant while the app stays open.',
         'details': ['You can stop sharing; leaving the screen or trip expiry ends it.', 'Permission, network or stale readings can interrupt updates. This is not emergency monitoring.'], 'faq_anchor': 'location-voice'},
        {'id': 'costs', 'title': 'Keep shared costs clear', 'body': 'When enabled, review the owner’s declared fuel, tolls and own share before agreeing your contribution.',
         'details': ['Declared costs are not independently verified; opening UPI does not prove payment. Receipt and refunds are recorded manually.'], 'faq_anchor': 'contributions'},
        {'id': 'reviews', 'title': 'Reviews & support', 'body': 'Rate an eligible completed trip, or use report and block for a relevant person or booking.',
         'details': ['Ratings require both the trip and your segment to be complete; public comments need your consent.', 'Reporting or blocking does not settle a payment or replace emergency help.'], 'faq_anchor': 'trust'},
        {'id': 'account', 'title': 'Stay in control of your account', 'body': 'Eligible phone members can save an optional recovery code or request account deletion after resolving active rides and payments.',
         'details': ['Recovery needs your saved code and a new phone verification. Deletion retains limited history and restricted safety records.'], 'faq_anchor': 'account'},
    ],
}
COPY['te']['journey'] = {
    'eyebrow': 'ప్లాన్ నుంచి ప్రయాణం వరకు',
    'title': 'ఒకే దారి. ప్రతి అడుగూ స్పష్టంగా.',
    'body': 'సీటు వెతకడం నుంచి కలిసి గమ్యం చేరే వరకు—ప్రయాణంలో ప్రతి అడుగూ తెలుసుకోండి.',
    'progress_label': 'యాప్‌లో ఏమున్నాయి?',
    'stops': [
        {'id': 'plan', 'title': 'మీ రూట్‌తో మొదలుపెట్టండి', 'body': 'ఎక్కడ ఎక్కాలి, ఎక్కడ దిగాలి, ఏ సమయంలో వెళ్లాలో ఇచ్చి సరిపోయే ట్రిప్‌లు చూడండి.',
         'details': ['మ్యాప్‌లో పాయింట్లు, రూట్ అంచనాలు చూసుకోండి. వెతికినంత మాత్రాన సీటు రిజర్వ్ కాదు.', 'నేటివ్ యాప్‌లో ఇంగ్లీష్, తెలుగు వాయిస్ ఇన్‌పుట్ పరీక్షిస్తున్నాం. వెబ్‌లో పికప్, దిగే చోటు టైప్ చేయండి.'], 'faq_anchor': 'location-voice'},
        {'id': 'offer', 'title': 'మీ ప్రయాణంలో సీట్లు షేర్ చేయండి', 'body': 'ముందే వెళ్లాలని ప్లాన్ చేసిన ట్రిప్‌కు రూట్, బయలుదేరే సమయం, ఖాళీ సీట్లు ఇవ్వండి.',
         'details': ['ట్రిప్ పెట్టడానికి డాక్యుమెంట్ల ఆమోదం చెల్లుబాటులో ఉండాలి.', 'ఏ రిక్వెస్ట్ అంగీకరించాలో మీ ఇష్టం. ఇది వెంటనే వచ్చే ట్యాక్సీ సర్వీస్ కాదు.'], 'faq_anchor': 'getting-started'},
        {'id': 'driver', 'title': 'డ్రైవర్ ప్రొఫైల్ చూడండి', 'body': 'యజమాని ప్రొఫైల్, కారు, డాక్యుమెంట్ సమీక్ష స్థితి, పూర్తయిన ట్రిప్‌ల రేటింగ్‌లు చూసుకోండి.',
         'details': ['యజమాని లైసెన్స్, RC, ఇన్సూరెన్స్, సెల్ఫీ సమీక్షకు పంపాలి.', 'డాక్యుమెంట్లు సమీక్షించారంటే పోలీస్ క్లియరెన్స్ లేదా భద్రతకు హామీ కాదు.'], 'faq_anchor': 'trust'},
        {'id': 'request', 'title': 'రిక్వెస్ట్ పంపండి. అంగీకారం కోసం వేచి ఉండండి.', 'body': 'కలిసే చోటు చూసి సీటు అడగండి. యజమాని అంగీకరించాకే సీటు ఖరారు.',
         'details': ['నా ట్రిప్‌లలో బుకింగ్ స్థితి చూడవచ్చు.', 'రద్దు బటన్ అందుబాటులో ఉంటే వాడి ఫలితం చూసుకోండి. రద్దుతో డబ్బు ఆటోమేటిక్‌గా తిరిగి రాదు.'], 'faq_anchor': 'requests'},
        {'id': 'chat', 'title': 'కలిసే వివరాలు మాట్లాడుకోండి', 'body': 'అంగీకరించిన బుకింగ్‌లో అవతలి వ్యక్తితో చాట్ చేయండి.',
         'details': ['పికప్ చోటు నిర్ధారించుకోండి. ప్లాన్ మారితే చెప్పండి.'], 'faq_anchor': 'requests'},
        {'id': 'live', 'title': 'మీ ఇష్టంతో లొకేషన్ షేర్ చేయండి', 'body': 'యాప్ తెరిచి ఉన్నప్పుడు, అంగీకరించిన ట్రిప్‌లోని అవతలి వ్యక్తితో లొకేషన్ పంచుకోవచ్చు.',
         'details': ['ఎప్పుడైనా ఆపవచ్చు. స్క్రీన్ వదిలినా, ట్రిప్ గడువు ముగిసినా షేరింగ్ ఆగుతుంది.', 'పర్మిషన్, నెట్‌వర్క్ లేదా పాత లొకేషన్ వల్ల అప్‌డేట్లు ఆగవచ్చు. ఇది అత్యవసర పర్యవేక్షణ కాదు.'], 'faq_anchor': 'location-voice'},
        {'id': 'costs', 'title': 'పంచుకునే ఖర్చు ముందే చూసుకోండి', 'body': 'సౌకర్యం అందుబాటులో ఉంటే, యజమాని చెప్పిన ఇంధనం, టోల్, తమ వాటా చూసి మీ మొత్తం ఒప్పుకోండి.',
         'details': ['చెప్పిన ఖర్చులను యాప్ స్వయంగా నిర్ధారించదు. UPI తెరిచినంత మాత్రాన పేమెంట్ కాదు. డబ్బు అందడం, రీఫండ్ వివరాలు ఇద్దరూ నమోదు చేయాలి.'], 'faq_anchor': 'contributions'},
        {'id': 'reviews', 'title': 'రివ్యూలు, సహాయం', 'body': 'అర్హత ఉన్న పూర్తయిన ట్రిప్‌కు రేటింగ్ ఇవ్వండి. అవసరమైతే సంబంధిత వ్యక్తి లేదా బుకింగ్‌ను రిపోర్ట్ చేయండి, బ్లాక్ చేయండి.',
         'details': ['ట్రిప్‌తో పాటు మీ ప్రయాణ భాగం పూర్తవాలి. మీ సమ్మతితోనే కామెంట్ అందరికీ కనిపిస్తుంది.', 'రిపోర్ట్ లేదా బ్లాక్‌తో పేమెంట్ సమస్య పరిష్కారం కాదు; అత్యవసర సహాయానికి బదులూ కాదు.'], 'faq_anchor': 'trust'},
        {'id': 'account', 'title': 'మీ అకౌంట్ మీ చేతుల్లో', 'body': 'అర్హత ఉన్న ఫోన్ సభ్యులు రికవరీ కోడ్ దాచుకోవచ్చు. నడుస్తున్న ట్రిప్‌లు, పేమెంట్ సమస్యలు ముగిశాక అకౌంట్ తొలగించమని కోరవచ్చు.',
         'details': ['రికవరీకి దాచుకున్న కోడ్, కొత్త ఫోన్ నిర్ధారణ కావాలి. అకౌంట్ తొలగించినా పరిమిత చరిత్ర, భద్రత రికార్డులు మిగులుతాయి.'], 'faq_anchor': 'account'},
    ],
}
for _language in ('en', 'te'):
    for _stop in COPY[_language]['journey']['stops']:
        _stop['link_label'] = 'Read the details' if _language == 'en' else 'పూర్తి వివరాలు చూడండి'


def normalize_public_language(language):
    lang = language.lower() if isinstance(language, str) and len(language) == 2 else 'en'
    return lang if lang in COPY else 'en'


def public_site_context(*, page, language, app_name, registration_enabled, payments_enabled,
                        support_email, operator_configured):
    """Return bounded plain-text content and same-origin links, never trusted HTML."""
    lang = normalize_public_language(language)
    copy = deepcopy(COPY[lang])
    if lang == 'en':
        registration = ('Phone sign-up is enabled. Verify your number and complete your profile and required consent before using member actions.' if registration_enabled else
                        'Public phone sign-up is not available in this beta yet. Opening the app does not create an account.')
        payments = ('Direct UPI is available after you agree the contribution, if both accounts have verified phone numbers and the owner’s documents are approved and current. The owner confirms receipt; refunds are handled between participants.' if payments_enabled else
                    'Direct UPI payments are not available in this beta yet. The app cannot open a payment for you right now.')
    else:
        registration = ('ఫోన్‌తో కొత్త అకౌంట్ చేసుకోవచ్చు. సభ్యుల పనులు వాడే ముందు నంబర్ నిర్ధారించి, ప్రొఫైల్, అవసరమైన సమ్మతి పూర్తి చేయండి.' if registration_enabled else
                        'ఈ బీటాలో కొత్తవారికి ఫోన్ సైన్ అప్ ఇంకా ప్రారంభించలేదు. యాప్ తెరిచినంత మాత్రాన అకౌంట్ తయారు కాదు.')
        payments = ('ఇద్దరి ఫోన్ నంబర్లు నిర్ధారణై, యజమాని డాక్యుమెంట్ల ఆమోదం, గడువు చెల్లుబాటులో ఉంటే, ఖర్చు ఒప్పుకున్నాక UPI వాడవచ్చు. డబ్బు అందిందని యజమాని నిర్ధారించాలి. రీఫండ్ ఇద్దరూ మాట్లాడుకుని చేయాలి.' if payments_enabled else
                    'ఈ బీటాలో నేరుగా UPI చెల్లింపు సౌకర్యం ఆపి ఉంది. ప్రస్తుతం యాప్ నుంచి లైవ్ పేమెంట్ లింక్ అందుబాటులో లేదు.')
    copy['beta_status'] = (('Phone sign-up available' if registration_enabled else 'Private beta')
                           if lang == 'en' else
                          ('ఫోన్ సైన్ అప్ అందుబాటులో ఉంది' if registration_enabled else 'ప్రైవేట్ బీటా'))
    copy['availability'].update(registration=registration, payments=payments)
    copy['faq_groups'][0]['items'][1]['answer'] = registration
    copy['faq_groups'][2]['items'][0]['answer'] = payments
    for stop in copy['journey']['stops']:
        anchor = stop['faq_anchor']
        if anchor not in {'getting-started', 'requests', 'contributions', 'trust', 'location-voice', 'account'}:
            raise ValueError('Unknown journey FAQ anchor')
        stop['href'] = '/faq?lang=' + lang + '#' + anchor
        if stop['id'] == 'costs':
            stop['status'] = payments
        elif stop['id'] == 'account':
            stop['status'] = registration
    email = support_email if isinstance(support_email, str) and len(support_email) <= 254 and re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", support_email) else ''
    if not operator_configured or not email:
        copy['support_body'] = copy['support_unavailable']
    current = '/faq' if page == 'faq' else '/welcome'
    return {'page': page, 'lang': lang, 'copy': copy, 'app_name': str(app_name)[:80],
            'registration_enabled': bool(registration_enabled), 'payments_enabled': bool(payments_enabled),
            'operator_configured': bool(operator_configured), 'support_email': email if operator_configured else '',
            'links': {**{key: path + '?lang=' + lang for key, path in
                        [('landing', '/welcome'), ('faq', '/faq'), ('app', '/'), ('terms', '/terms'), ('privacy', '/privacy')]},
                      'en': current + '?lang=en', 'te': current + '?lang=te'}}
