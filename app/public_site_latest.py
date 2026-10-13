"""Approved SeatPal five-stage presentation, composed with current live capabilities.

Source: seatpal-motion-20261013-r3. This module does not configure services.
"""
from copy import deepcopy
from .public_site import public_site_context

DESIGN_COPY = {'en': {'facts': [{'title': 'A trip already planned',
                   'body': 'Share the costs of a journey the owner already planned. A seat depends on someone offering '
                           'a matching trip; it is not an on-demand taxi.'},
                  {'title': 'You choose what to share',
                   'body': 'Choose whether to share your location with the people in your accepted trip while the app '
                           'is open. You can stop sharing.'},
                  {'title': 'Review the details yourself',
                   'body': 'Document review and completed-trip ratings provide context. They cannot guarantee anyone’s '
                           'safety.'}],
        'layered': {'corridor_label': 'Our first corridor',
                    'origin': 'Hyderabad',
                    'destination': 'Mahabubnagar',
                    'corridor_note': 'A pilot for private owners and people going the same way. Check the app for '
                                     'matching trips.',
                    'story_title': 'One journey. Two ways to join.',
                    'story_body': 'Looking for a seat or already planning a trip? Start with the journey you actually '
                                  'want to make.',
                    'rider_heading': 'Your next seat starts here.',
                    'owner_heading': 'Make room for someone going your way.',
                    'faq_heading': 'A few things before you go.',
                    'faq_link': 'Explore all FAQs',
                    'final_title': 'Your route could be someone else’s, too.',
                    'final_body': 'Open the app to explore the beta. A seat request is confirmed only when the owner '
                                  'accepts.'},
        'character': {'plan': {'title': 'Plan your way',
                               'body': 'A familiar route. A little room to choose who you travel with.'},
                      'travel': {'title': 'Travel together',
                                 'body': 'Agree the details, say hello, and keep each other in the loop.'},
                      'terms': {'title': 'On your terms',
                                'body': 'Clear costs. Honest feedback. Your information, with choices that stay '
                                        'yours.'}},
        'dimension': {'notes': 'Good to know',
                      'illustration': 'How it works, illustrated',
                      'from': 'Pickup',
                      'to': 'Drop-off',
                      'when': 'Your date and time',
                      'route_title': 'Start with your route',
                      'seat': 'One personal seat',
                      'request': 'Request a seat',
                      'accept': 'If the owner accepts',
                      'meet': 'Agree where to meet',
                      'coordination': 'Talk after acceptance',
                      'costs': 'Agree the trip costs',
                      'fuel': 'Fuel and tolls',
                      'share': 'The owner contributes too',
                      'location': 'Location sharing',
                      'choice': 'Your choice to share'},
        'mobility': {'label': 'Ride types',
                     'car': 'Car',
                     'bike': 'Motorbike',
                     'note': 'Bike rides aren’t available in this beta yet.'},
        'seat_brand': {'description': 'A passenger seat changes from car cabin to motorcycle pillion, then returns to '
                                      'the SeatPal mark. A brand illustration, not a booking option.',
                       'replay': 'Replay animation'},
        'five_stage': {'title': ['Shared rides.', 'Your way.'],
                       'body': 'A seat on someone’s planned journey. A little company on yours. Start with the '
                               'Hyderabad–Mahabubnagar pilot.',
                       'explore': 'Follow the journey',
                       'example': 'How it works · illustrated',
                       'your_plan': 'Have a spare seat',
                       'their_plan': 'Need a ride',
                       'shared_way': 'Travel together',
                       'merge_description': 'The driver travels the full planned route. A passenger joins at pickup, '
                                            'shares only the highlighted section, and leaves at drop-off. The driver '
                                            'continues. This is an illustration, not a geographic map.',
                       'ride_story': {'owner': 'Driver’s planned trip',
                                      'driver': 'Driver',
                                      'passenger': 'Passenger',
                                      'pickup': 'Pickup',
                                      'join': 'The passenger joins.',
                                      'shared': 'Travel together for this section.',
                                      'dropoff': 'Drop-off',
                                      'leave': 'The passenger gets off.',
                                      'continues': 'The driver continues.',
                                      'planned': 'Full planned route',
                                      'segment': 'Shared section only',
                                      'caption': 'Illustration only · not a map or live trip',
                                      'replay': 'Replay journey'},
                       'checklist': ['Vehicle details', 'Document review status', 'Pickup and drop-off'],
                       'pending': 'See pending',
                       'accepted': 'See accepted',
                       'pending_title': 'Your request comes first.',
                       'pending_body': 'The owner has not accepted yet. Your seat is not confirmed.',
                       'accepted_title': 'An agreement, from both sides.',
                       'accepted_body': 'If the owner accepts, coordinate the meeting point and review any eligible '
                                        'cost agreement.',
                       'stopped': 'See sharing off',
                       'sharing': 'See sharing on',
                       'stopped_title': 'Your location stays yours.',
                       'stopped_body': 'Sharing is optional. No location is being shared in this illustration.',
                       'sharing_title': 'Only for this part of the journey.',
                       'sharing_body': 'In an eligible accepted trip, you choose to share while the app is open. You '
                                       'can stop; arrival or expiry ends it.',
                       'finish': ['Journey ends', 'Location sharing ends', 'Review, if eligible'],
                       'stages': [{'id': 'find',
                                   'name': 'Find',
                                   'title': 'Two plans. One direction.',
                                   'body': 'Start with where you want to go. Find a compatible journey, or offer room '
                                           'on one you already planned.',
                                   'stops': ['plan', 'offer']},
                                  {'id': 'check',
                                   'name': 'Check',
                                   'title': 'Know who. Know where.',
                                   'body': 'A matching route is just the start. Look at the person, the vehicle and '
                                           'the places you will meet.',
                                   'stops': ['driver']},
                                  {'id': 'agree',
                                   'name': 'Agree',
                                   'title': 'Make the details mutual.',
                                   'body': 'Request first. Wait for acceptance. Talk through the meeting point and any '
                                           'shared costs before departure.',
                                   'stops': ['request', 'chat', 'costs']},
                                  {'id': 'meet',
                                   'name': 'Meet',
                                   'title': 'Together. On your terms.',
                                   'body': 'Keep each other informed without giving up control of your location.',
                                   'stops': ['live']},
                                  {'id': 'arrive',
                                   'name': 'Arrive',
                                   'title': 'A clear ending. A better next ride.',
                                   'body': 'End the sharing window, leave an eligible review, and keep control of your '
                                           'account.',
                                   'stops': ['reviews', 'account']}]}},
 'te': {'hero': {'eyebrow': 'హైదరాబాద్ ↔ మహబూబ్\u200cనగర్',
                 'title': 'ఒకే దారినా? కలిసి వెళ్దాం.',
                 'body': 'మీ దారిలో వెళ్లే ట్రిప్\u200cలో సీటు చూసుకోండి. లేదా మీ ట్రిప్\u200cలో ఖాళీ సీట్లు షేర్ '
                         'చేయండి. వివరాలు మాట్లాడుకుని, ఖర్చు పంచుకుని, కలిసి వెళ్లండి.',
                 'cta': 'యాప్ తెరవండి'},
        'facts': [{'title': 'ముందే ప్లాన్ చేసిన ప్రయాణం',
                   'body': 'ఇది ప్రైవేట్ ప్రయాణంలో ఖర్చు పంచుకోవడం. వెంటనే వచ్చే ట్యాక్సీ సర్వీస్ కాదు; రైడ్ '
                           'దొరుకుతుందనే హామీ లేదు.'},
                  {'title': 'ఏం పంచుకోవాలో మీ ఇష్టం',
                   'body': 'అంగీకరించిన ట్రిప్\u200cలో ఉన్నవారితో మాత్రమే, యాప్ తెరిచి ఉన్నప్పుడు మీ లొకేషన్ '
                           'పంచుకోవచ్చు. ఎప్పుడైనా ఆపవచ్చు.'},
                  {'title': 'వివరాలు మీరూ చూసుకోండి',
                   'body': 'డాక్యుమెంట్ సమీక్ష, పూర్తయిన ట్రిప్\u200cల రేటింగ్\u200cలు కొంత సమాచారం ఇస్తాయి. ఎవరి '
                           'భద్రతకూ అవి హామీ కావు.'}],
        'layered': {'corridor_label': 'మొదట ఈ రూట్\u200cలో',
                    'origin': 'హైదరాబాద్',
                    'destination': 'మహబూబ్\u200cనగర్',
                    'corridor_note': 'ఒకే దారిలో వెళ్లే వారి కోసం ఈ పైలట్. మీకు సరిపోయే ట్రిప్ యాప్\u200cలో చూడండి.',
                    'story_title': 'ఒకే దారి. కలిసి వెళ్దాం.',
                    'story_body': 'సీటు కావాలా? మీ ట్రిప్\u200cలో చోటుందా? మీరు వెళ్లాలనుకున్న ట్రిప్\u200cతో '
                                  'మొదలుపెట్టండి.',
                    'rider_heading': 'మీకు సీటు కావాలంటే…',
                    'owner_heading': 'మీ దారిలో వెళ్లేవారికి సీటు ఇవ్వండి.',
                    'faq_heading': 'వెళ్లే ముందు కొన్ని విషయాలు.',
                    'faq_link': 'అన్ని సందేహాలు చూడండి',
                    'final_title': 'మీ దారిలో ఇంకొకరూ వెళ్తుండొచ్చు.',
                    'final_body': 'బీటా చూడటానికి యాప్ తెరవండి. యజమాని అంగీకరించాకే మీ సీటు కన్ఫర్మ్ అవుతుంది.'},
        'journey': {'eyebrow': 'ప్లాన్ నుంచి ప్రయాణం వరకు',
                    'title': 'ఒకే దారి. ప్రతి అడుగూ స్పష్టంగా.',
                    'body': 'సీటు వెతకడం నుంచి కలిసి గమ్యం చేరే వరకు—ప్రయాణంలో ప్రతి అడుగూ తెలుసుకోండి.',
                    'progress_label': 'యాప్\u200cలో ఏమున్నాయి?',
                    'stops': [{'id': 'plan',
                               'title': 'మీ రూట్\u200cతో మొదలుపెట్టండి',
                               'body': 'ఎక్కడ ఎక్కాలి, ఎక్కడ దిగాలి, ఏ సమయంలో వెళ్లాలో ఇచ్చి సరిపోయే ట్రిప్\u200cలు '
                                       'చూడండి.',
                               'details': ['మ్యాప్\u200cలో పాయింట్లు, రూట్ అంచనాలు చూసుకోండి. వెతికినంత మాత్రాన సీటు '
                                           'రిజర్వ్ కాదు.',
                                           'నేటివ్ యాప్\u200cలో ఇంగ్లీష్, తెలుగు వాయిస్ ఇన్\u200cపుట్ '
                                           'పరీక్షిస్తున్నాం. వెబ్\u200cలో పికప్, దిగే చోటు టైప్ చేయండి.'],
                               'faq_anchor': 'location-voice',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'offer',
                               'title': 'మీ ప్రయాణంలో సీట్లు షేర్ చేయండి',
                               'body': 'ముందే వెళ్లాలని ప్లాన్ చేసిన ట్రిప్\u200cకు రూట్, బయలుదేరే సమయం, ఖాళీ సీట్లు '
                                       'ఇవ్వండి.',
                               'details': ['ట్రిప్ పెట్టడానికి డాక్యుమెంట్ల ఆమోదం చెల్లుబాటులో ఉండాలి.',
                                           'ఏ రిక్వెస్ట్ అంగీకరించాలో మీ ఇష్టం. ఇది వెంటనే వచ్చే ట్యాక్సీ సర్వీస్ '
                                           'కాదు.'],
                               'faq_anchor': 'getting-started',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'driver',
                               'title': 'డ్రైవర్ ప్రొఫైల్ చూడండి',
                               'body': 'యజమాని ప్రొఫైల్, వాహనం, డాక్యుమెంట్ సమీక్ష స్థితి, పూర్తయిన ట్రిప్\u200cల '
                                       'రేటింగ్\u200cలు చూసుకోండి.',
                               'details': ['యజమాని లైసెన్స్, RC, ఇన్సూరెన్స్, సెల్ఫీ సమీక్షకు పంపాలి.',
                                           'డాక్యుమెంట్లు సమీక్షించారంటే పోలీస్ క్లియరెన్స్ లేదా భద్రతకు హామీ కాదు.'],
                               'faq_anchor': 'trust',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'request',
                               'title': 'రిక్వెస్ట్ పంపండి. అంగీకారం కోసం వేచి ఉండండి.',
                               'body': 'కలిసే చోటు చూసి సీటు అడగండి. యజమాని అంగీకరించాకే సీటు ఖరారు.',
                               'details': ['నా ట్రిప్\u200cలలో బుకింగ్ స్థితి చూడవచ్చు.',
                                           'రద్దు బటన్ అందుబాటులో ఉంటే వాడి ఫలితం చూసుకోండి. రద్దుతో డబ్బు '
                                           'ఆటోమేటిక్\u200cగా తిరిగి రాదు.'],
                               'faq_anchor': 'requests',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'chat',
                               'title': 'కలిసే వివరాలు మాట్లాడుకోండి',
                               'body': 'అంగీకరించిన బుకింగ్\u200cలో అవతలి వ్యక్తితో చాట్ చేయండి.',
                               'details': ['పికప్ చోటు నిర్ధారించుకోండి. ప్లాన్ మారితే చెప్పండి.'],
                               'faq_anchor': 'requests',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'live',
                               'title': 'మీ ఇష్టంతో లొకేషన్ షేర్ చేయండి',
                               'body': 'యాప్ తెరిచి ఉన్నప్పుడు, అంగీకరించిన ట్రిప్\u200cలోని అవతలి వ్యక్తితో లొకేషన్ '
                                       'పంచుకోవచ్చు.',
                               'details': ['ఎప్పుడైనా ఆపవచ్చు. స్క్రీన్ వదిలినా, ట్రిప్ గడువు ముగిసినా షేరింగ్ '
                                           'ఆగుతుంది.',
                                           'పర్మిషన్, నెట్\u200cవర్క్ లేదా పాత లొకేషన్ వల్ల అప్\u200cడేట్లు ఆగవచ్చు. '
                                           'ఇది అత్యవసర పర్యవేక్షణ కాదు.'],
                               'faq_anchor': 'location-voice',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'costs',
                               'title': 'పంచుకునే ఖర్చు ముందే చూసుకోండి',
                               'body': 'సౌకర్యం అందుబాటులో ఉంటే, యజమాని చెప్పిన ఇంధనం, టోల్, తమ వాటా చూసి మీ మొత్తం '
                                       'ఒప్పుకోండి.',
                               'details': ['చెప్పిన ఖర్చులను యాప్ స్వయంగా నిర్ధారించదు. UPI తెరిచినంత మాత్రాన పేమెంట్ '
                                           'కాదు. డబ్బు అందడం, రీఫండ్ వివరాలు ఇద్దరూ నమోదు చేయాలి.'],
                               'faq_anchor': 'contributions',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'reviews',
                               'title': 'రివ్యూలు, సహాయం',
                               'body': 'అర్హత ఉన్న పూర్తయిన ట్రిప్\u200cకు రేటింగ్ ఇవ్వండి. అవసరమైతే సంబంధిత వ్యక్తి '
                                       'లేదా బుకింగ్\u200cను రిపోర్ట్ చేయండి, బ్లాక్ చేయండి.',
                               'details': ['ట్రిప్\u200cతో పాటు మీ ప్రయాణ భాగం పూర్తవాలి. మీ సమ్మతితోనే కామెంట్ '
                                           'అందరికీ కనిపిస్తుంది.',
                                           'రిపోర్ట్ లేదా బ్లాక్\u200cతో పేమెంట్ సమస్య పరిష్కారం కాదు; అత్యవసర '
                                           'సహాయానికి బదులూ కాదు.'],
                               'faq_anchor': 'trust',
                               'link_label': 'పూర్తి వివరాలు చూడండి'},
                              {'id': 'account',
                               'title': 'మీ అకౌంట్ మీ చేతుల్లో',
                               'body': 'అర్హత ఉన్న ఫోన్ సభ్యులు రికవరీ కోడ్ దాచుకోవచ్చు. నడుస్తున్న ట్రిప్\u200cలు, '
                                       'పేమెంట్ సమస్యలు ముగిశాక అకౌంట్ తొలగించమని కోరవచ్చు.',
                               'details': ['రికవరీకి దాచుకున్న కోడ్, కొత్త ఫోన్ నిర్ధారణ కావాలి. అకౌంట్ తొలగించినా '
                                           'పరిమిత చరిత్ర, భద్రత రికార్డులు మిగులుతాయి.'],
                               'faq_anchor': 'account',
                               'link_label': 'పూర్తి వివరాలు చూడండి'}]},
        'character': {'plan': {'title': 'మీ దారిని ప్లాన్ చేసుకోండి',
                               'body': 'తెలిసిన దారే. ఎవరితో వెళ్లాలో వివరాలు చూసుకుని ఎంచుకోండి.'},
                      'travel': {'title': 'కలిసి ప్రయాణించండి',
                                 'body': 'వివరాలు మాట్లాడుకోండి. పలకరించుకోండి. ప్లాన్ మారితే చెప్పుకోండి.'},
                      'terms': {'title': 'వివరాలు మీ చేతుల్లో',
                                'body': 'ఖర్చు స్పష్టంగా. అభిప్రాయం నిజాయితీగా. మీ సమాచారం పంచుకోవడంలో మీ ఇష్టం.'}},
        'dimension': {'notes': 'తెలుసుకోవాల్సినవి',
                      'illustration': 'ఇలా పని చేస్తుంది',
                      'from': 'ఎక్కే చోటు',
                      'to': 'దిగే చోటు',
                      'when': 'మీ తేదీ, సమయం',
                      'route_title': 'మీ దారితో మొదలుపెట్టండి',
                      'seat': 'మీ కోసం ఒక సీటు',
                      'request': 'సీటు అడగండి',
                      'accept': 'యజమాని అంగీకరిస్తే',
                      'meet': 'కలిసే చోటు మాట్లాడుకోండి',
                      'coordination': 'అంగీకారం తర్వాత చాట్',
                      'costs': 'ప్రయాణ ఖర్చు ఒప్పుకోండి',
                      'fuel': 'ఇంధనం, టోల్ ఖర్చు',
                      'share': 'యజమానీ తన వాటా చెల్లిస్తారు',
                      'location': 'లొకేషన్ షేరింగ్',
                      'choice': 'పంచుకోవడం మీ ఇష్టం'},
        'mobility': {'label': 'రైడ్ రకాలు',
                     'car': 'కారు',
                     'bike': 'మోటార్\u200cబైక్',
                     'note': 'ఈ బీటాలో బైక్ రైడ్\u200cలు ఇంకా అందుబాటులో లేవు.'},
        'seat_brand': {'description': 'ప్రయాణికుల సీటు కారు క్యాబిన్\u200cలో కనిపించి, తర్వాత మోటార్\u200cబైక్ వెనుక '
                                      'సీటుగా మారి, మళ్లీ SeatPal చిహ్నంగా కనిపిస్తుంది. ఇది బ్రాండ్ యానిమేషన్ '
                                      'మాత్రమే, బుకింగ్ ఎంపిక కాదు.',
                       'replay': 'యానిమేషన్ మళ్లీ చూడండి'},
        'five_stage': {'title': ['మీ దారిలో.', 'కలిసి వెళ్దాం.'],
                       'body': 'వాళ్లు ప్లాన్ చేసిన ట్రిప్\u200cలో మీకో సీటు. మీ ప్రయాణంలో కాస్త తోడు. '
                               'హైదరాబాద్–మహబూబ్\u200cనగర్ పైలట్\u200cతో మొదలుపెట్టండి.',
                       'explore': 'ప్రయాణం ఎలా సాగుతుందో చూడండి',
                       'example': 'ఇలా పని చేస్తుంది · ఉదాహరణ',
                       'your_plan': 'ఖాళీ సీటు ఉందా?',
                       'their_plan': 'రైడ్ కావాలా?',
                       'shared_way': 'కలిసి ప్రయాణించండి',
                       'merge_description': 'డ్రైవర్ ముందే ప్లాన్ చేసిన దారిలో వెళ్తారు. ప్రయాణికుడు పికప్ వద్ద చేరి, '
                                            'రంగుతో చూపిన భాగంలోనే కలిసి వెళ్లి, డ్రాప్ వద్ద దిగుతారు. డ్రైవర్ ముందుకు '
                                            'వెళ్తారు. ఇది ఉదాహరణ మాత్రమే, భౌగోళిక మ్యాప్ కాదు.',
                       'ride_story': {'owner': 'డ్రైవర్ ప్లాన్ చేసిన ట్రిప్',
                                      'driver': 'డ్రైవర్',
                                      'passenger': 'ప్రయాణికుడు',
                                      'pickup': 'పికప్',
                                      'join': 'ప్రయాణికుడు చేరుతారు.',
                                      'shared': 'ఈ భాగంలో కలిసి వెళ్తారు.',
                                      'dropoff': 'డ్రాప్',
                                      'leave': 'ప్రయాణికుడు దిగుతారు.',
                                      'continues': 'డ్రైవర్ ముందుకు వెళ్తారు.',
                                      'planned': 'ప్లాన్ చేసిన మొత్తం దారి',
                                      'segment': 'కలిసి వెళ్లే భాగం మాత్రమే',
                                      'caption': 'ఉదాహరణ మాత్రమే · మ్యాప్ లేదా లైవ్ ట్రిప్ కాదు',
                                      'replay': 'మళ్లీ చూపించండి'},
                       'checklist': ['వాహనం వివరాలు', 'డాక్యుమెంట్ల సమీక్ష స్థితి', 'ఎక్కే, దిగే చోటు'],
                       'pending': 'పెండింగ్ ఉదాహరణ',
                       'accepted': 'అంగీకరించిన ఉదాహరణ',
                       'pending_title': 'ముందుగా ఒక రిక్వెస్ట్.',
                       'pending_body': 'యజమాని ఇంకా అంగీకరించలేదు. మీ సీటు ఇంకా ఖరారు కాలేదు.',
                       'accepted_title': 'ఇద్దరూ మాట్లాడుకుని ఒప్పుకోండి.',
                       'accepted_body': 'యజమాని అంగీకరిస్తే కలిసే చోటు మాట్లాడుకోండి. అందుబాటులో ఉంటే ప్రయాణ ఖర్చు '
                                        'ఒప్పందం చూసుకోండి.',
                       'stopped': 'షేరింగ్ ఆఫ్ ఉదాహరణ',
                       'sharing': 'షేరింగ్ ఆన్ ఉదాహరణ',
                       'stopped_title': 'మీ లొకేషన్ మీ చేతుల్లో.',
                       'stopped_body': 'పంచుకోవడం మీ ఇష్టం. ఈ ఉదాహరణలో ఎవరి లొకేషన్ షేర్ కావడం లేదు.',
                       'sharing_title': 'ఈ ప్రయాణ భాగం వరకే.',
                       'sharing_body': 'అర్హత ఉన్న అంగీకరించిన ట్రిప్\u200cలో యాప్ తెరిచి ఉండగా మీ ఇష్టంతో '
                                       'పంచుకోవచ్చు. ఎప్పుడైనా ఆపవచ్చు. చేరుకున్నా, గడువు ముగిసినా ఆగుతుంది.',
                       'finish': ['ప్రయాణం ముగుస్తుంది', 'లొకేషన్ షేరింగ్ ఆగుతుంది', 'అర్హత ఉంటే రివ్యూ ఇవ్వండి'],
                       'stages': [{'id': 'find',
                                   'name': 'వెతకండి',
                                   'nav_label': 'వెతుకు',
                                   'title': 'రెండు ప్లాన్\u200cలు. ఒకే దారి.',
                                   'body': 'మీరు వెళ్లాలనుకున్న చోటుతో మొదలుపెట్టండి. సరిపోయే ట్రిప్ చూసుకోండి లేదా '
                                           'ముందే ప్లాన్ చేసిన మీ ట్రిప్\u200cలో చోటు ఇవ్వండి.',
                                   'stops': ['plan', 'offer']},
                                  {'id': 'check',
                                   'name': 'చూసుకోండి',
                                   'nav_label': 'చూడు',
                                   'title': 'ఎవరితో? ఎక్కడి నుంచి?',
                                   'body': 'దారి కలిస్తే సరిపోదు. వ్యక్తి, వాహనం, కలిసే చోటు వివరాలు చూసుకోండి.',
                                   'stops': ['driver']},
                                  {'id': 'agree',
                                   'name': 'ఒప్పుకోండి',
                                   'nav_label': 'ఒప్పుకో',
                                   'title': 'వివరాలు ఇద్దరికీ స్పష్టంగా.',
                                   'body': 'ముందు రిక్వెస్ట్. తర్వాత యజమాని అంగీకారం. బయలుదేరే ముందు కలిసే చోటు, '
                                           'పంచుకునే ఖర్చు మాట్లాడుకోండి.',
                                   'stops': ['request', 'chat', 'costs']},
                                  {'id': 'meet',
                                   'name': 'కలవండి',
                                   'nav_label': 'కలవు',
                                   'title': 'తోడు ఉంటుంది. మీ ఇష్టమూ ఉంటుంది.',
                                   'body': 'ఒకరికొకరు సమాచారం చెప్పుకోండి. లొకేషన్ పంచుకోవాలా వద్దా మీరే ఎంచుకోండి.',
                                   'stops': ['live']},
                                  {'id': 'arrive',
                                   'name': 'చేరుకోండి',
                                   'nav_label': 'చేరు',
                                   'title': 'ఈ ట్రిప్ ముగింపు. మరో మంచి ప్రయాణానికి మొదలు.',
                                   'body': 'షేరింగ్ ముగుస్తుంది. అర్హత ఉంటే రివ్యూ ఇవ్వండి. మీ అకౌంట్ మీ చేతుల్లోనే '
                                           'ఉంటుంది.',
                                   'stops': ['reviews', 'account']}]}}}


def public_site_latest_context(*, landing_path="/welcome", **kwargs):
    context = public_site_context(**kwargs)
    lang = context["lang"]
    current_stops = {stop["id"]: stop for stop in context["copy"]["journey"]["stops"]}
    context["copy"].update(deepcopy(DESIGN_COPY[lang]))
    stops = context["copy"]["journey"]["stops"]
    for stop in stops:
        current = current_stops[stop["id"]]
        stop["href"] = current["href"]
        if "status" in current:
            stop["status"] = current["status"]
    by_id = {stop["id"]: stop for stop in stops}
    for stage in context["copy"]["five_stage"]["stages"]:
        stage["features"] = [by_id[key] for key in stage["stops"]]
    # Paths are fixed by the route dispatcher, never taken from user input.
    if landing_path not in {"/welcome", "/welcome/latest"}:
        raise ValueError("Unknown latest landing path")
    context["links"].update(landing=landing_path + "?lang=" + lang,
                            en=landing_path + "?lang=en", te=landing_path + "?lang=te")
    context["comparison_url"] = "/welcome/previous?lang=" + lang
    context["comparison_label"] = "Previous design" if lang == "en" else "మునుపటి డిజైన్"
    return context
