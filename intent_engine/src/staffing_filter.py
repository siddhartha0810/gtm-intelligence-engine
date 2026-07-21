"""
Filters IT staffing firms and systems-integrator partners from company signals.
Vertical-agnostic — the SI/staffing blocklist below is major consulting firms
(Accenture, Deloitte, KPMG, etc.), not tied to any one vendor's ecosystem.

Key philosophy:
  - If a signal comes FROM an SI firm (IBM, PwC, Wipro, etc.), we don't
    simply drop it — we first try to extract the END CLIENT from the
    description. If a client is found, the signal is CONVERTED to use
    the client company instead. Only dropped if no client can be extracted.
  - Pure body-shopping / staffing firms with no client info are always dropped.

Three-level approach:
  1. Try end-client extraction for known SI partners
  2. Exact normalised-name blocklist (fastest, catches major firms)
  3. Keyword heuristic on company name (catches long-tail staffing firms)
"""

import re
from src.utils import get_logger, clean_text, is_valid_company_name

logger = get_logger(__name__)

# ── Major SI partners — we try client extraction BEFORE dropping ─────────────
# These firms post job ads and case studies on behalf of end clients.
_SI_PARTNERS: set[str] = {
    # ── Big 4 & global management consulting ─────────────────────────────────
    "accenture", "accenture federal services", "accenture consulting",
    "deloitte", "deloitte consulting", "deloitte digital", "deloitte touche",
    "kpmg", "kpmg consulting", "kpmg advisory",
    "pwc", "pricewaterhousecoopers", "pwc consulting",
    "ernst young", "ey", "ey consulting", "ernst & young",
    "grant thornton", "grant thornton llp",
    "bdo", "bdo digital", "bdo consulting",
    "rsm", "rsm us", "rsm consulting",
    "crowe", "crowe llp",
    "moss adams", "plante moran",
    "mckinsey", "mckinsey & company",
    "bcg", "boston consulting group",
    "bain", "bain & company",
    "oliver wyman", "roland berger",
    "a.t. kearney", "kearney",
    # ── Global IT services / offshore SIs ────────────────────────────────────
    "ibm", "ibm consulting", "ibm global business services", "ibm gbs",
    "ibm global services", "ibm issc",
    "infosys", "infosys bpm", "infosys consulting",
    "wipro", "wipro limited", "wipro technologies",
    "tcs", "tata consultancy services", "tata consulting",
    "hcl", "hcl technologies", "hcltech", "hcl infosystems",
    "tech mahindra", "tech mahindra limited",
    "mphasis", "mphasis limited",
    "cognizant", "cognizant technology solutions",
    "capgemini", "capgemini consulting", "capgemini sogeti",
    "birlasoft", "birlasoft limited",
    "hexaware", "hexaware technologies",
    "zensar", "zensar technologies",
    "ntt data", "ntt data services", "ntt",
    "dxc technology", "dxc", "dxc consulting",
    "unisys", "unisys corporation",
    "atos", "atos consulting", "atos origin",
    "sopra steria", "sopra consulting",
    "fujitsu", "fujitsu consulting",
    "logicalis", "logicalis group",
    "stefanini", "stefanini group",
    "igate", "igate corporation",
    "ciber", "ciber consulting",
    "epam systems", "epam",
    "globant",
    "slalom", "slalom consulting",
    "thoughtworks",
    "publicis sapient", "sapient", "sapient consulting", "sapient corporation",
    "avanade",
    "rizing",
    "saic", "science applications international",
    "leidos", "mantech",
    "booz allen hamilton", "booz allen",
    "cgi", "cgi group", "cgi federal",
    "dimension data", "ntt dimension data",
    "sirius computer solutions", "sirius",
    "presidio",
    "softchoice",
    "cdw", "cdw corporation",
    "insight direct", "insight enterprises",
    "computacenter",
    "wesco international", "wesco",
    "bertelsmann", "arvato",
    "mindtree",
    "lti", "larsen toubro infotech", "ltimindtree",
    "persistent systems",
    "niit technologies", "niit",
    # ── JDE-specific SIs ─────────────────────────────────────────────────────
    "syntax", "syntax systems",
    "denovo", "denovo consulting",
    "terillium",
    "steltix",
    "resolution it",
    "collaborate business solutions", "cbs",
    "velocity technology solutions",
    "jade global",
    "everge group", "everge",
    "astute business solutions",
    "baker tilly digital", "baker tilly",
    "hitachi solutions", "hitachi consulting",
    "spinnaker support",
    "rimini street",
    "lortek",
    "xtend it",
    "mastek", "mastech",
    "namos", "namos solutions",
    "evosys", "keste", "certus", "mythics",
    "circular edge",
    "edgewater consulting",
    "clarkston consulting",
    "sierra-cedar", "sierra cedar",
    "collaborative solutions",

    "linium",
    "xellera informatics", "xellera",
    "unilogix", "unilogix solutions",
    "redrock consulting",
    "bluefin solutions", "bluefin",
    "cedar consulting",
    "benchmark solutions",
    "ifs consultants", "ifs world",
    # ── Oracle-specific consulting brands ────────────────────────────────────
    "oracle consulting", "oracle cloud consulting",
    "sierra systems",   # acquired by ntt data
    "deloitte federal",
    "accenture technology solutions",
    "rounding group",
    # ── Global management / IT consulting firms not yet listed ────────────────
    "west monroe", "west monroe partners",  # management/IT consulting
    "protiviti",                            # IT risk / internal audit consulting
    "huron consulting", "huron",            # healthcare/higher-ed consulting
    "fti consulting", "fti",               # business consulting
    "navigant",                            # consulting (merged into Guidehouse)
    "bearingpoint",                        # management consulting brand
    "pa consulting group", "pa consulting",  # UK innovation consulting
    "aon hewitt", "aon consulting",         # HR consulting
    "mercer",                              # HR/benefits consulting
    "towers watson", "wtwco", "wtw",       # global advisory
    "hay group",                           # management consulting
    "sibson consulting",
    "hackett group",                       # benchmarking/consulting
    "isg", "information services group",   # IT research/advisory
    "everest group",                       # IT analyst/consulting
    "horses for sources", "hfs research",  # IT services research
    "gartner consulting",
    "idc", "idc consulting",              # research/advisory
    "forrester",                           # research/advisory
    # ── Regional ERP/JDE consulting firms (global) ───────────────────────────
    "zalaris",                             # Scandinavian HCM consulting
    "innovia consulting",                  # JDE/Oracle consulting
    "aptean",                              # ERP vendor/consulting
    "jde consulting australia",
    "fusion5",                             # ANZ Oracle/JDE consulting
    "empired",                            # ANZ IT services
    "versent",                            # ANZ Oracle Cloud consulting
    "dxc eclipse",                         # ANZ Oracle/JDE consulting (DXC brand)
    "clover hr",                          # HCM consulting
    "britec",                             # UK Oracle consulting
    "team it solutions",                  # Oracle consulting
    "brite solutions",                    # Oracle consulting
    "hexaware technologies",              # already have hexaware
    "nttdata", "ntt data corporation", "ntt data japan",
    "ibm japan", "ibm india", "ibm uk", "ibm australia",
    "wipro uk", "wipro australia",
    "infosys australia", "infosys europe", "infosys uk",
    "tata consultancy australia", "tata consultancy uk",
    "capgemini uk", "capgemini australia", "capgemini india",
    "cognizant uk", "cognizant australia",
    # ── JDE/Oracle consulting firms missing from original list ────────────────
    "datamap",                           # Oracle/JDE consulting
    "infovity",                          # Oracle Cloud/JDE consulting
    "argano",                            # Oracle/JDE consulting (incl. former Edgewater)
    "eone infotech", "eone",             # Oracle consulting
    "net at work",                       # ERP consulting (Acumatica/JDE)
    "maini consulting",                  # Oracle consulting
    "peloton consulting group", "peloton consulting",  # ERP consulting
    "riveron",                           # business/IT consulting
    "vidorra consulting group", "vidorra consulting",  # Oracle consulting
    "alithya",                           # Oracle/JDE consulting (Canada-based)
    "aris amplify",                      # Oracle consulting
    "centraprise",                       # Oracle consulting
    "centroid systems",                  # Oracle Cloud consulting
    "critical river", "criticalriver",   # Oracle consulting
    "elire",                             # Oracle/ERP consulting
    "orabase solutions", "orabase",      # Oracle consulting
    "project partners",                  # Oracle partner / JDE consulting
    "speridian technologies", "speridian",  # Oracle consulting/staffing hybrid
    "vc5 consulting", "vc5",             # Oracle consulting
    "woodlawn consulting", "woodlawn consulting group",  # Oracle consulting
    "xtivia",                            # Oracle/JDE/ERP consulting
    "360 ide",                           # JDE-specific consulting firm
    "datavail",                          # Oracle DBA managed services
    "sdp presence", "sdi presence",      # Oracle consulting
    "turnberry solutions", "turnberry",  # Oracle/IT consulting
    "metaxphase", "metaphase",           # government IT consulting
    "bluecrux",                          # supply chain consulting (posts for clients)
    "guidehouse",                        # management/IT consulting
    "impact advisors",                   # healthcare IT consulting
    "kearney & company", "kearney and company",  # government accounting/consulting
    "bdo usa", "bdo",                    # accounting/advisory (already have bdo in list? check)
    "opportune",                         # energy advisory/consulting
    "saliense",                          # government/defense IT consulting
    "makse group", "makse",              # management consulting
    "enspire partners", "enspire",       # IT consulting
    # ── Large IT services firms that act as SIs ───────────────────────────────
    "conduent",                          # large BPO/IT services — posts for client engagements
    "genpact",                           # BPO/IT services
    "infinite computer solutions", "infinite computer",  # IT services/staffing
    "general dynamics information technology", "gdit",  # government IT contractor
    "chugach government solutions",      # government contractor
    "turner & townsend", "turner and townsend",  # project management consulting
    "coforge",                           # IT services/BPO (Indian SI)
    "itc infotech",                      # IT services (ITC subsidiary)
    "intelliswift",                      # IT staffing brand of LTTS
    "innovaway",                         # Italian IT services
    "wsp in the us", "wsp",              # engineering consulting (rarely posts for clients)
    # ── Oracle product/tool vendors (not end-user prospects) ─────────────────
    "opkey",                             # Oracle automated testing tool vendor
    "planisware",                        # project portfolio mgmt software vendor
    "levelpath",                         # procurement software vendor
    "insightsoftware",                   # financial software vendor (not a JDE end user)
    "compport",                          # compensation software vendor
    "prometheus group", "prometheus",    # Oracle EAM software vendor
    "vic.ai",                            # AP automation software vendor
}

# ── Pure staffing / body-shopping — always drop, no client extraction ────────
_PURE_STAFFING: set[str] = {
    # US staffing
    "robert half", "robert half technology", "robert half international",
    "kforce", "teksystems", "tek systems", "insight global",
    "cybercoders", "modis", "staffmark", "staffmark group",
    "volt information sciences", "volt",
    "randstad", "randstad technologies", "randstad sourceright",
    "adecco", "adecco group",
    "manpower", "manpowergroup", "manpower group",
    "experis",  # manpower's it brand
    "kelly services", "kelly", "kellyocg",
    "spherion",
    "apex group", "apex systems",
    "allegis group", "allegis",
    "aerotek",  # allegis brand
    "teksystems",  # allegis brand
    "pontoon solutions", "pontoon",
    "recruitment solutions",
    "global consultants",
    # IT/ERP-focused recruiters and staffing (frequent LinkedIn false positives)
    "net2source", "n2s",
    "jobot",                      # recruiting platform
    "mastech digital",            # mastech is SI partner, mastech digital is pure staffing
    "ampcus",                     # normalized form (strips " inc")
    "hyr global source", "hyr global",
    "brooksource",
    "neerinfo solutions", "neerinfo",
    "vbeyond",                    # normalized form (strips " corporation")
    "jackson james",              # Oracle/JDE-specific recruiter
    "inspyr solutions", "inspyr",
    "plastic executive recruiters", "plastic executive",
    "redleo software", "redleo",
    "r systems",                  # IT staffing (different from r system)
    "swits digital",              # normalized form handles "Private Limited"
    "balin technologies", "balin",
    "catch resource management", "catch resource",  # JDE/ERP recruiter
    "tenth revolution", "frank recruitment",  # ERP staffing (strips " group")
    "akkodis",                    # formerly modis — IT staffing brand
    "american unit",              # normalized (strips ", Inc" after comma fix)
    "pacer",                      # normalized form of "Pacer Group" (strips " group")
    "erock",
    "biospace",                   # biotech job board, not an end user
    # ── UK staffing ──────────────────────────────────────────────────────────
    "harvey nash", "harvey nash group",
    "hays", "hays recruitment", "hays technology", "hays plc",
    "pagegroup", "michael page", "page executive",
    "spring group", "spring technology",
    "computer futures",
    "penna",
    "sos recruitment",
    "blue arrow", "blue arrow staffing",
    "gi group",
    "cpl resources", "cpl group",
    "morgan hunt",
    "nrl group",
    "la international",
    "robert walters",                    # global exec search, UK-founded
    "sthree",                            # UK IT staffing
    "gartner",                           # research/advisory (not a JDE end user)
    "lorien",                            # UK IT staffing
    "reed technology", "reed recruitment",  # UK staffing (NOT "reed" alone — too generic)
    "manpower uk",
    "nes fircroft", "nes global talent", "fircroft",  # energy/engineering staffing
    "spencer ogden",                     # energy sector staffing
    "matchtech",                         # engineering staffing (UK)
    "electus recruitment",               # engineering staffing (UK)
    "opus recruit",
    "twentyfirst",                       # IT staffing (UK)
    "sanderson",                         # IT staffing (UK)
    "search",                            # Scottish IT staffing
    "csc", "computer sciences corporation", "computer sciences",  # IT services (CSC)
    "capita",                            # UK outsourcing/staffing
    "amey",                              # UK services/staffing
    # ── Continental Europe staffing ───────────────────────────────────────────
    "brunel",                            # Netherlands engineering staffing
    "usg people",                        # Netherlands staffing (Recruit)
    "unique", "unique interim",          # Netherlands staffing
    "tempo-team",                        # Belgium/Netherlands (Randstad brand)
    "dis ag", "dis",                     # Germany staffing (DIS AG, strips " ag" → "dis")
    "hofmann",                           # Germany staffing
    "persona service",                   # Germany staffing
    "trenkwalder",                       # Austria/Central Europe staffing
    "lutech",                            # Italy IT staffing
    "hdi global",                        # staffing
    "axon",                              # European IT staffing
    "digital talent",                    # European IT staffing
    "mercuri urval",                     # Sweden executive search
    "european recruitment",              # generic European recruiter
    "manpower france", "manpower germany", "manpower europe",
    "adecco france", "adecco germany", "adecco spain",
    "page personnel",                    # PageGroup brand
    "michael page technology",
    "mazars",                            # Global accounting/consulting (not end user)
    "pa consulting",                     # UK management consulting
    "atos consulting",                   # already in SI partners via "atos"
    # ── Australia / New Zealand staffing ──────────────────────────────────────
    "paxus",                             # Australia IT staffing
    "peoplebank",                        # Australia IT staffing
    "finite recruitment", "finite",      # Australia IT staffing
    "talent international",              # Australia IT staffing
    "candle it", "candle",               # Australia IT staffing
    "teksouth",                          # Australia IT staffing
    "hudson",                            # Australia/NZ executive search
    "manpower australia",
    "hays australia", "hays new zealand",
    "modis australia",
    "michael page australia",
    "programmed",                        # Australia workforce solutions
    "sevaan group",                      # Australia engineering staffing
    "hays asia pacific",
    "robert half australia",
    "davidson",                          # Australia staffing
    "people2people",                     # Australia staffing
    "mp & silva",                        # NZ staffing
    "persolkelly", "persol kelly",       # Asia/Pacific staffing (Kelly + Persol JV)
    # ── Middle East staffing (common for JDE energy/construction roles) ───────
    "nadia", "nadia global",             # UAE staffing
    "charterhouse", "charterhouse partnership",  # UAE executive search
    "gulf connexions",                   # Bahrain IT/finance staffing
    "bayt", "bayt.com",                  # Middle East job board
    "irecruit",                          # Middle East recruiting
    "hays middle east",
    "michael page middle east",
    "robert half middle east",
    "talentmate",                        # UAE staffing
    "niku staffing",
    "transearch",                        # Middle East executive search
    "nassau group",
    # ── Asia / Southeast Asia staffing ────────────────────────────────────────
    "peoplesearch",                      # Singapore IT staffing
    "kerry consulting",                  # Singapore executive search
    "spring professional",               # Adecco brand Asia
    "links international",               # Hong Kong/Asia staffing
    "bgc group",                         # Hong Kong IT staffing
    "heidrick & struggles",              # global exec search
    "jac recruitment",                   # Japan/Asia staffing
    "robert walters asia",
    "michael page asia",
    "hays asia",
    "kelly asia",
    "ranstad asia",
    "recruit holdings",                  # Japan staffing giant
    "pasona",                            # Japan staffing
    "temp holdings",                     # Japan staffing
    "staffgroup",                        # Singapore staffing
    "singapore technologies staffing",
    "persolkelly asia",
    "adecco asia",
    "dhl express", "dhl supply chain",   # logistics (not JDE end user in the consulting sense)
    # ── Canada staffing ───────────────────────────────────────────────────────
    "procom",                            # Canada IT staffing
    "s.i. systems", "si systems",        # Canada IT staffing
    "eagle professional resources", "eagle",  # Canada IT staffing
    "brainhunter",                       # Canada IT staffing
    "veritaaq",                          # Canada IT staffing
    "futurestep",                        # Korn Ferry recruiting brand
    "adecco canada", "adecco groupe",
    "hays canada",
    "randstad canada",
    "manpower canada",
    "michael page canada",
    "goldbeck recruiting",               # Canada technical recruiting
    "hire authority",                    # Canada staffing
    "mindsource",                        # Canada IT staffing
    # ── Latin America staffing ────────────────────────────────────────────────
    "softtek",                           # Mexico IT services/staffing
    "neoris",                            # Mexico IT consulting/services
    "everis", "nttdata everis",          # Spain/LATAM consulting (now NTT Data)
    "stefanini latin america",           # already have stefanini
    "adecco latam", "adecco latin",
    "randstad latam", "randstad mexico",
    "manpower mexico", "manpower brasil",
    "page personnel latam",
    # ── Africa / South Africa staffing ───────────────────────────────────────
    "adcorp",                            # South Africa staffing
    "pnet",                              # South Africa job board
    "communicate recruitment",           # South Africa staffing
    "msp consulting",                    # South Africa IT staffing
    "ioco",                              # South Africa IT staffing
    "olico",                             # South Africa staffing
    # ── Global executive search firms ────────────────────────────────────────
    "korn ferry",                        # global executive search
    "heidrick and struggles", "heidrick",  # global executive search
    "spencer stuart",                    # global executive search
    "egon zehnder",                      # global executive search
    "russell reynolds", "russell reynolds associates",  # executive search
    "odgers berndtson",                  # global executive search
    "boyden",                            # global executive search
    "amrop",                             # global executive search
    "stanton chase",                     # global executive search
    "horton international",
    # India staffing
    "teamlease", "teamlease services",
    "quess corp", "quess",
    "firstsource",
    "rchilli",
    "info edge",                         # India (Naukri/99acres parent)
    "naukri",                            # India job board
    "careernet",                         # India staffing
    "abc consultants",                   # India executive search
    "global hunt",                       # India executive search
    "mafoi management", "mafoi",         # India staffing
    "ikya human capital",                # India staffing
    "innovsource",                       # India staffing
    "ciel hr",                           # India staffing
    "genius consultants",                # India staffing
    "adecco india",
    "randstad india",
    "manpower india", "manpowergroup india",
    "hays india",
    # ── Small IT staffing / body-shop firms (frequent LinkedIn false positives) ─
    # Identified from live DB scan May 2026
    "accruepartners", "accruepart",      # IT staffing
    "agile resources",                   # IT staffing
    "airswift",                          # energy/engineering staffing
    "ajulia executive search",           # executive recruiter
    "alexander technology group", "alexander technology",  # IT staffing
    "altimetrik",                        # IT staffing/consulting
    "amtex systems",                     # IT staffing
    "astir it solutions",                # IT staffing
    "bayone solutions",                  # IT staffing
    "beacon hill",                       # IT staffing
    "belcan",                            # engineering/IT staffing
    "bright vision technologies",        # IT staffing
    "business information group", "business information",  # IT staffing
    "calfus",                            # Oracle consulting/staffing
    "citizant",                          # government IT consulting/staffing
    "cogent data solutions",             # IT staffing
    "comresource",                       # IT staffing
    "comtech global",                    # IT staffing
    "corsource",                         # IT staffing
    "crowdplat",                         # IT staffing
    "datum technologies",                # IT staffing
    "delmock technologies",              # IT staffing
    "devfi",                             # IT staffing
    "dsj global",                        # supply chain staffing
    "e-solutions",                       # IT staffing
    "elsdon group", "elsdon",            # IT staffing
    "envision technology solutions", "envision technology",  # IT staffing
    "everest consultants",               # IT staffing
    "excelon solutions",                 # IT staffing (not Exelon the utility company)
    "find great people", "fgp",          # recruiting firm
    "flexon technologies",               # IT staffing
    "govcon associates",                 # government IT staffing
    "greymatter solutions",              # IT staffing
    "hireart",                           # recruiting marketplace
    "hireright",                         # background check / HR firm (not a JDE prospect)
    "idr",                               # IT staffing
    "indotronix avani", "indotronix",    # IT staffing
    "infojini",                          # IT staffing
    "infospeed services", "infospeed",   # IT staffing
    "intellibee",                        # IT staffing
    "intersources",                      # IT staffing
    "it minds",                          # IT staffing
    "itnova",                            # IT staffing
    "jcw group", "jcw",                  # financial/ERP staffing
    "jmd technologies",                  # IT staffing
    "jmj phillip group", "jmj phillip",  # executive search
    "kainos innovative solutions",       # IT staffing (not Kainos plc software)
    "kaizen technologies",               # IT staffing
    "ledgent",                           # accounting/finance staffing
    "lentech",                           # IT staffing
    "lorven technologies", "lorven",     # IT staffing
    "lucayan technology solutions",      # IT staffing
    "lvi associates", "lvi",             # engineering staffing
    "macalogic",                         # IT staffing/consulting
    "matlen silver",                     # IT staffing
    "medasource",                        # healthcare IT staffing
    "metrix it solutions",               # IT staffing
    "midland-marvel recruiters", "midland-marvel",  # IT recruiter
    "mks",                               # IT staffing (not MKS Instruments the manufacturer)
    "mondo",                             # IT staffing/recruiting
    "my3tech",                           # IT staffing
    "nasscomm",                          # IT staffing
    "navstar",                           # IT staffing
    "npaworldwide",                      # recruiting network
    "o2 technologies",                   # IT staffing
    "peersource",                        # IT staffing
    "pine services group", "pine services",  # IT staffing
    "purple hires",                      # IT recruiting
    "pyramid consulting",                # IT staffing
    "quest search and selection",        # recruiting
    "radiant",                           # IT staffing
    "resource informatics group", "resource informatics",  # IT staffing
    "richard wayne & roberts", "richard wayne and roberts",  # IT staffing
    "risingsun technologies",            # IT staffing
    "russell tobin",                     # IT/finance staffing
    "saicon",                            # IT consulting/staffing
    "saransh",                           # IT staffing
    "sharp services",                    # IT staffing
    "shr consulting group", "shr consulting",  # IT staffing
    "sibitalent",                        # IT staffing
    "signify technology",                # tech recruiting
    "silicontek",                        # IT staffing
    "soft",                              # IT consulting/staffing (SOFT Inc.)
    "softworld",                         # IT staffing (Kelly brand)
    "spectraforce",                      # IT staffing
    "stellar consulting solutions",      # IT staffing
    "steps talent",                      # talent/staffing
    "strategic systems",                 # IT staffing
    "systech international", "systech",  # IT staffing
    "talentfish",                        # IT staffing
    "talently",                          # recruiting
    "talent portus",                     # talent agency
    "tech tandem",                       # IT staffing
    "techgene solutions", "techgene",    # IT staffing
    "technix",                           # IT staffing
    "techwish",                          # IT staffing
    "tekfortune",                        # IT staffing
    "themesoft",                         # IT staffing
    "theoris",                           # IT staffing/consulting
    "theron solutions", "theron",        # IT staffing
    "tier4 group", "tier4",              # IT staffing/consulting
    "ttc group", "tech talent consulting",  # IT recruiting
    "twentyai",                          # AI/tech recruiting
    "us tech solutions", "us tech",      # IT staffing
    "vailexa",                           # IT staffing
    "vika talent solutions", "vika talent",  # talent/staffing
    "vinsys information technology", "vinsys",  # IT staffing
    "visionaire partners", "visionaire", # IT staffing/consulting
    "vlink",                             # IT staffing
    "volantsoft",                        # IT staffing
    "vrk it vision",                     # IT staffing
    "vsb tech consulting", "vsb tech",   # IT staffing
    "vytwo technologies",                # IT staffing
    "william everett",                   # IT staffing/recruiting
    "woodsage",                          # IT staffing/consulting
    # ── Anonymously posted jobs — company identity unknown ────────────────────
    "confidential", "confidential careers", "confidential jobs",
    "undisclosed",
    # ── Malformed entries (job titles captured as company names) ──────────────
    "senior erp payroll", "international",
    # Oracle itself is not a prospect
    "oracle america", "oracle corporation", "oracle",
    "oracle uk", "oracle emea",
    # ── Finance/banking recruiting — the Endex-ICP equivalent of the IT/ERP
    # recruiters above. IB/PE job titles ("Investment Banking Associate") are
    # frequently posted BY these agencies on behalf of an undisclosed client,
    # so the agency itself surfaces as the "company" unless filtered here —
    # confirmed live: 5 of the Endex ICP campaign's top-15 scored prospects
    # were recruiting agencies, not end-user financial firms.
    "selby jennings",                    # Phaidon Group — banking/finance recruiting
    "alexander chapman",                 # finance recruiting (UK)
    "crossing hurdles",                  # finance recruiting (UK)
    "blacklock group",                   # executive search
    "venture search",                    # recruiting agency
    "tenfold search", "tenfold search & advisory",  # search/advisory
    "atlantic group", "the atlantic group",  # finance & accounting staffing (Vaco brand)
    "lawrence harvey",                   # tech/finance recruiting
    "bruin", "bruin financial",          # financial services recruiting
}

# ── Keyword patterns that indicate staffing / body-shopping ─────────────────
_STAFFING_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(staffing|recruiting|recruitment|resourcing)\b", re.I),
    re.compile(r"\b(staff augment|body shop|body-shop|outstaffing)\b", re.I),
    re.compile(r"\b(talent acquisition|talent solutions|workforce solutions)\b", re.I),
    re.compile(r"\b(contract staffing|contingent workforce|temp agency)\b", re.I),
    re.compile(r"\b(executive search|search firm|headhunter|headhunting)\b", re.I),
    re.compile(r"\b(job board|career portal|employment agency|placement agency)\b", re.I),
    # "Talent" anywhere as a word-start in company name → almost always a staffing brand
    # Matches: STEPS Talent, TalentFish, Talently, Talent360, Talent Space, Vika Talent
    # Word-start only (not mid-word) — \btalent without trailing \b catches "Talent360.ai" too
    re.compile(r"\btalent", re.I),
    # "Hires" in company name → Purple Hires, HireArt, etc.
    re.compile(r"\bhires?\b", re.I),
    # "Search and Selection" — standard recruiter phrase
    re.compile(r"\bsearch and selection\b", re.I),
    # Common Indian IT body-shop suffixes that indicate staffing
    re.compile(r"\b(it source|tech source|erp source|it resourcing)\b", re.I),
    # Catch regional variants of known global staffing brands automatically.
    # Only include brand names specific enough that they won't false-positive
    # on legitimate end-user companies. Single common words (hudson, reed, kelly)
    # are kept in the explicit set only — not here.
    re.compile(
        r"\b(hays|randstad|adecco|manpower|pagegroup|modis|persolkelly|akkodis"
        r"|spencer ogden|fircroft|nes global|harvey nash|robert walters|robert half"
        r"|michael page|page executive|spring professional"
        r"|korn ferry|spencer stuart|egon zehnder|russell reynolds"
        r"|odgers berndtson|boyden|amrop|stanton chase|heidrick)\b",
        re.I,
    ),
]

# ── Keyword patterns that flag an SI / consulting firm (not staffing) ────────
_SI_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(erp consulting|erp implementation|erp partner|oracle partner)\b", re.I),
    re.compile(r"\b(jde partner|jd edwards partner|jde consulting|jde implementation)\b", re.I),
    re.compile(r"\b(systems integrator|systems integration|si partner)\b", re.I),
    re.compile(r"\b(implementation partner|delivery partner|solution partner)\b", re.I),
    re.compile(r"\bmanaged services\b", re.I),
]

# Job title patterns indicating a contractor role FOR a client
_CONTRACTOR_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(contract(or)?|freelance|c2c|corp.?to.?corp)\b", re.I),
    re.compile(r"\b(resource manager|bench resource|resource pool)\b", re.I),
]

# ── Patterns to extract END CLIENT from SI job postings / descriptions ───────
_END_CLIENT_PATTERNS: list[re.Pattern] = [
    # "for our client, Barratt Developments"
    re.compile(
        r"for\s+(?:our\s+(?:key\s+)?client|a\s+(?:key\s+)?client)[,:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|located|who|is|a\s)|\.|,|$)",
        re.I,
    ),
    # "end client: National Grid"
    re.compile(
        r"end[\s\-]?client[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "client: BP plc" or "client name: BP"
    re.compile(
        r"\bclient(?:\s+name)?[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "deployed at / working at / on-site at Rolls Royce"
    re.compile(
        r"(?:deployed\s+at|working\s+at|on[\s\-]?site\s+at|based\s+at)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|is)|\.|,|$)",
        re.I,
    ),
    # "on behalf of Barratt"
    re.compile(
        r"on\s+behalf\s+of\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:in|based|to|for)|\.|,|$)",
        re.I,
    ),
    # "helps [Client] implement JD Edwards" — SI success story pattern
    re.compile(
        r"(?:helps?|assisted?|enabled?|implemented?\s+for|deployed?\s+for)\s+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=\s+(?:to|with|achieve|improve|transform|implement|deploy|migrate))",
        re.I,
    ),
    # "[Client] selects / goes live / migrates"
    re.compile(
        r"^([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)\s+(?:selects?|goes?\s+live|went\s+live|migrates?|implements?|upgrades?|deploys?)",
        re.I,
    ),
    # "customer: [Client]" or "organisation: [Client]"
    re.compile(
        r"(?:customer|organisation|organization)[:\s]+([A-Z][A-Za-z0-9\s&',\.\-]{2,50}?)(?=[\.\,]|$)",
        re.I,
    ),
]

# Words that indicate we extracted the SI name, not the client
_SI_WORDS: set[str] = {
    "accenture", "deloitte", "pwc", "kpmg", "ey", "ibm", "infosys",
    "wipro", "hcl", "tcs", "capgemini", "cgi", "ntt", "dxc", "unisys",
    "syntax", "denovo", "terillium", "steltix", "mastek", "mastech",
    "namos", "evosys", "keste", "certus", "mythics", "birlasoft",
    "hexaware", "zensar", "mphasis", "cognizant", "mindtree",
    "spinnaker", "rimini", "oracle", "microsoft", "sap",
    # Extended
    "atos", "sopra", "fujitsu", "logicalis", "stefanini", "epam",
    "globant", "slalom", "thoughtworks", "sapient", "publicis",
    "avanade", "rizing", "saic", "leidos", "booz", "sirius",
    "presidio", "hitachi", "baker", "grant", "rsm", "bdo", "crowe",
    "circular", "edgewater", "clarkston", "sierra", "collaborative",
    "linium", "xellera", "unilogix", "redrock", "bluefin", "cedar",
    "benchmark", "lti", "larsen", "persistent", "niit",
    "tech mahindra", "dimension", "computacenter", "cdw", "insight",
}


def _normalise(name: str) -> str:
    """
    Full normalisation: clean, strip decorations, strip all known suffixes.
    Returns the most-reduced form used for exact blocklist matching.
    """
    name = clean_text(name)
    # Strip pipe-separated DBA/brand suffixes: "Find Great People | FGP" → "Find Great People"
    name = re.sub(r'\s*\|.*$', '', name).strip()
    # Strip parenthetical annotations: "(N2S)", "(formerly Modis)", "(An LTTS Company)"
    name = re.sub(r'\s*\([^)]*\)', '', name).strip()
    # Strip domain-style TLD branding: "Talent360.ai" → "Talent360", "Tech.io" → "Tech"
    name = re.sub(r'\.(ai|io|co|com|net|org|app|tech)\b', ' ', name, flags=re.I)
    name = re.sub(r'\s+', ' ', name).strip()
    # Strip dash-separated parent/description suffixes: "Brand - A XYZ Company"
    name = re.sub(r'\s+-\s+.*$', '', name).strip()
    # Strip ", a/an [Parent] Company" tails: "Softworld, a Kelly Company"
    name = re.sub(r',?\s+(a|an)\s+\w[\w\s]+company\s*$', '', name, flags=re.I).strip()
    # Normalise remaining commas before legal suffixes: "Unit, Inc" → "Unit Inc"
    name = re.sub(r',\s*', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Strip all legal entity and descriptor suffixes
    all_suffixes = [
        " inc", " inc.", " corp", " corp.", " corporation", " ltd", " ltd.", " llc",
        " l.l.c", " group", " co.", " co", " gmbh", " s.a.", " plc",
        " ag", " nv", " bv", " lp", " llp",
        " private limited", " pvt ltd", " pvt. ltd", " limited",
        " services", " solutions", " technologies", " technology",
        " systems", " global", " international", " consulting",
    ]
    low = name.lower()
    # Strip up to 3 levels of suffix to handle chains like "Tech Consulting Services"
    for _ in range(3):
        for s in all_suffixes:
            if low.endswith(s) and len(low) > len(s) + 2:
                name = name[: -len(s)].strip()
                low = name.lower()
                break
    return low.strip()


def _normalise_partial(name: str) -> str:
    """
    Partial normalisation: strip decorations and legal entity suffixes only.
    Keeps descriptor words like 'group', 'solutions', 'technologies'.
    Used as a second-pass check to match blocklist entries that include those words.
    """
    name = clean_text(name)
    name = re.sub(r'\s*\|.*$', '', name).strip()
    name = re.sub(r'\s*\([^)]*\)', '', name).strip()
    name = re.sub(r'\s+-\s+.*$', '', name).strip()
    name = re.sub(r',?\s+(a|an)\s+\w[\w\s]+company\s*$', '', name, flags=re.I).strip()
    name = re.sub(r'\.(ai|io|co|com|net|org|app|tech)\b', ' ', name, flags=re.I)
    name = re.sub(r',\s*', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    legal_only = [
        " inc", " inc.", " corp", " corp.", " corporation", " ltd", " ltd.", " llc",
        " l.l.c", " co.", " gmbh", " s.a.", " plc", " ag", " nv", " bv", " lp", " llp",
        " private limited", " pvt ltd", " pvt. ltd", " limited",
        # Also strip " group" so "Datum Technologies Group, Inc." → "datum technologies"
        " group",
    ]
    low = name.lower()
    for s in legal_only:
        if low.endswith(s) and len(low) > len(s) + 2:
            name = name[: -len(s)].strip()
            low = name.lower()
    return low.strip()


def _is_si_partner(company_name: str) -> bool:
    norm = _normalise(company_name)
    partial = _normalise_partial(company_name)
    if norm in _SI_PARTNERS or partial in _SI_PARTNERS:
        return True
    for pat in _SI_KEYWORD_PATTERNS:
        if pat.search(company_name):
            return True
    return False


def _is_pure_staffing(company_name: str) -> bool:
    norm = _normalise(company_name)
    partial = _normalise_partial(company_name)
    if norm in _PURE_STAFFING or partial in _PURE_STAFFING:
        return True
    for pat in _STAFFING_PATTERNS:
        if pat.search(company_name):
            return True
    return False


def _is_contractor_signal(signal: dict) -> bool:
    title = signal.get("job_title", "")
    for pat in _CONTRACTOR_TITLE_PATTERNS:
        if pat.search(title):
            return True
    return False


def _extract_end_client(signal: dict) -> str:
    """
    Try to find the end client company in a signal that came from an SI firm.
    Checks job_title + description. Returns client name or empty string.
    """
    text = f"{signal.get('job_title', '')} {signal.get('description', '')}"
    for pat in _END_CLIENT_PATTERNS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip().rstrip(".,;:")
            # Reject if we just matched the SI firm itself
            if candidate.lower().split()[0] in _SI_WORDS:
                continue
            if is_valid_company_name(candidate) and len(candidate) > 3:
                return candidate
    return ""


def filter_signals(signals: list[dict]) -> tuple[list[dict], int]:
    """
    Process signals from SI partners and staffing firms:
      - SI partner signal WITH extractable end client → convert + keep
      - SI partner signal WITHOUT end client → drop
      - Pure staffing firm → always drop
      - Contractor title signal → attempt client extraction, else drop
    Returns (filtered_signals, removed_count).
    """
    kept, removed = [], 0

    for sig in signals:
        company = sig.get("company_name", "")

        # Pure staffing — no client extraction, always drop
        if _is_pure_staffing(company):
            logger.debug(f"Filtered (pure staffing): {company}")
            removed += 1
            continue

        # Known SI partner — try to extract end client
        if _is_si_partner(company):
            client = _extract_end_client(sig)
            if client:
                logger.debug(f"SI client extracted: {client} (via {company})")
                sig = dict(sig)  # don't mutate original
                sig["company_name"] = client
                sig["si_partner"] = company  # preserve who sourced it
                kept.append(sig)
            else:
                logger.debug(f"Filtered (SI, no client found): {company}")
                removed += 1
            continue

        # Contractor title — try client extraction, else drop
        if _is_contractor_signal(sig):
            client = _extract_end_client(sig)
            if client:
                logger.debug(f"Contractor client extracted: {client}")
                sig = dict(sig)
                sig["company_name"] = client
                kept.append(sig)
            else:
                logger.debug(f"Filtered (contractor title): {sig.get('job_title')} @ {company}")
                removed += 1
            continue

        kept.append(sig)

    return kept, removed


def is_staffing_firm(company_name: str) -> bool:
    """Public helper — used by aggregator to drop whole-company buckets."""
    return _is_pure_staffing(company_name) or _is_si_partner(company_name)
