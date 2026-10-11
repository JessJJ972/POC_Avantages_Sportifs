"""POC Avantages Sportifs: démonstration locale reproductible, sans secrets."""
import argparse,csv,datetime as dt,hashlib,json,logging,os,random,re,sqlite3,urllib.request,zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
COMPANY_ADDRESS='1362 Av. des Platanes, 34970 Lattes'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SPORTS=['Course à pied','Vélo','Randonnée','Natation','Tennis','Yoga','Escalade','Football']
SCHEMA='''
CREATE TABLE IF NOT EXISTS employee(employee_id INTEGER PRIMARY KEY,last_name TEXT NOT NULL,first_name TEXT NOT NULL,bu TEXT,gross_salary REAL NOT NULL,home_address TEXT,commute_mode TEXT,declared_sport TEXT);
CREATE TABLE IF NOT EXISTS activity(activity_id INTEGER PRIMARY KEY,employee_id INTEGER NOT NULL REFERENCES employee(employee_id),start_at TEXT NOT NULL,end_at TEXT NOT NULL,sport_type TEXT NOT NULL,distance_m INTEGER,elapsed_s INTEGER NOT NULL,comment TEXT,source TEXT NOT NULL, CHECK(distance_m IS NULL OR distance_m>=0),CHECK(elapsed_s>=0));
CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value REAL NOT NULL);
CREATE TABLE IF NOT EXISTS commute_check(employee_id INTEGER PRIMARY KEY REFERENCES employee(employee_id),distance_km REAL,status TEXT NOT NULL,source TEXT NOT NULL,detail TEXT);
CREATE TABLE IF NOT EXISTS pipeline_run(run_id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,ended_at TEXT,status TEXT NOT NULL,employees INTEGER DEFAULT 0,activities INTEGER DEFAULT 0,anomalies INTEGER DEFAULT 0,error_message TEXT);
CREATE TABLE IF NOT EXISTS anomaly(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT NOT NULL,employee_id INTEGER,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notification(activity_id INTEGER PRIMARY KEY,message TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
'''
DEFAULTS={'prime_rate':0.05,'wellbeing_activity_threshold':15,'wellbeing_days':5,'walk_max_km':15,'bike_max_km':25}

def excel_rows(path):
    """Read first worksheet of .xlsx using Python standard library; no external Excel dependency."""
    with zipfile.ZipFile(path) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings=[''.join(t.text or '' for t in node.findall('.//m:t',NS)) for node in root]
        root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        result=[]
        for row in root.findall('.//m:sheetData/m:row',NS):
            values={}
            for c in row.findall('m:c',NS):
                letters=re.match(r'[A-Z]+',c.attrib['r']).group()
                idx=0
                for letter in letters:idx=idx*26+ord(letter)-64
                v=c.find('m:v',NS)
                if c.attrib.get('t')=='s' and v is not None: val=strings[int(v.text)]
                elif c.attrib.get('t')=='inlineStr':val=''.join(t.text or '' for t in c.findall('.//m:t',NS))
                else:val=v.text if v is not None else ''
                values[idx-1]=val
            result.append([values.get(i,'') for i in range(max(values,default=-1)+1)])
        return result

def intval(v):return int(float(v))
def clean(v):return str(v or '').strip()
def normalize_mode(mode):
    s=clean(mode).lower()
    if 'marche' in s or 'pied' in s or 'running' in s: return 'walk'
    if 'vélo' in s or 'velo' in s or 'trottinette' in s: return 'bike'
    return 'other'

def commute_is_valid(mode,km,params=DEFAULTS):
    kind=normalize_mode(mode)
    if kind=='other':return None
    return km <= (params['walk_max_km'] if kind=='walk' else params['bike_max_km'])

def validate_activity(a):
    if a['elapsed_s']<0:raise ValueError('durée négative')
    if a['distance_m'] is not None and a['distance_m']<0:raise ValueError('distance négative')
    if a['end_at']<a['start_at']:raise ValueError('fin avant début')
    if not a['sport_type']:raise ValueError('sport manquant')

def google_route_distance_km(address,mode,key):
    """Google Routes API; request is optional and never executed without a key."""
    if not key:raise ValueError('GOOGLE_MAPS_API_KEY manquante')
    travel='WALK' if normalize_mode(mode)=='walk' else 'BICYCLE'
    payload={'origin':{'address':address},'destination':{'address':COMPANY_ADDRESS},'travelMode':travel,'computeAlternativeRoutes':False}
    req=urllib.request.Request('https://routes.googleapis.com/directions/v2:computeRoutes',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Goog-Api-Key':key,'X-Goog-FieldMask':'routes.distanceMeters'},method='POST')
    with urllib.request.urlopen(req,timeout=20) as resp:out=json.load(resp)
    routes=out.get('routes',[])
    if not routes:raise ValueError('itinéraire indisponible')
    return routes[0]['distanceMeters']/1000

def load_employees(rh_path,sport_path):
    sports={}
    for row in excel_rows(sport_path)[1:]:
        if not row or not clean(row[0]):continue
        try:identifier=intval(row[0])
        except ValueError:continue
        sport=clean(row[1]) if len(row)>1 else ''
        if sport:sports[identifier]=sport
    employees=[];seen=set();anomalies=[]
    for row in excel_rows(rh_path)[1:]:
        if len(row)<11 or not clean(row[0]):continue
        try:
            identifier=intval(row[0]);salary=float(row[6])
            if identifier in seen:raise ValueError('identifiant dupliqué')
            if salary<0:raise ValueError('salaire négatif')
            seen.add(identifier)
            employees.append((identifier,clean(row[1]),clean(row[2]),clean(row[4]),salary,clean(row[9]),clean(row[10]),sports.get(identifier,'')))
        except (ValueError,TypeError) as exc:anomalies.append(('rh',None,f'Ligne RH invalide: {exc}'))
    return employees,anomalies

def simulate(employees,seed=42,months=12):
    rng=random.Random(seed);now=dt.datetime.now().replace(hour=12,minute=0,second=0,microsecond=0)
    start=now-dt.timedelta(days=round(months*365.25/12));activities=[]
    for employee in employees:
        eid=employee[0];declared=employee[7]
        n=rng.randint(9,34) if declared else rng.randint(4,18)
        for _ in range(n):
            when=start+dt.timedelta(seconds=rng.randint(0,int((now-start).total_seconds())))
            sport=declared if declared and rng.random()<0.65 else rng.choice(SPORTS)
            secs=rng.randint(1200,7200)
            distance=None if any(x in sport.lower() for x in ['yoga','escalade','musculation','tennis','football','natation']) else rng.randint(1800,25000)
            a={'employee_id':eid,'start_at':when.isoformat(timespec='seconds'),'end_at':(when+dt.timedelta(seconds=secs)).isoformat(timespec='seconds'),'sport_type':sport,'distance_m':distance,'elapsed_s':secs,'comment':'Activité simulée pour le POC','source':'simulation'}
            validate_activity(a);activities.append(a)
    activities.sort(key=lambda a:(a['start_at'],a['employee_id']))
    return activities

def notification_message(employee,a):
    dist=f" ({a['distance_m']/1000:.1f} km)" if a['distance_m'] is not None else ''
    return f"Bravo {employee[2]} {employee[1]} ! Activité : {a['sport_type']}{dist}, durée {round(a['elapsed_s']/60)} min."

def send_slack(message,webhook):
    req=urllib.request.Request(webhook,data=json.dumps({'text':message}).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=10) as resp:resp.read()

def export_csv(con,path,query):
    cur=con.execute(query);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow([d[0] for d in cur.description]);writer.writerows(cur)

def build_exports(con,out):
    config=dict(con.execute('SELECT key,value FROM config'))
    employees=con.execute('SELECT * FROM employee').fetchall()
    counts=dict(con.execute('SELECT employee_id,COUNT(*) FROM activity GROUP BY employee_id'))
    commute={r['employee_id']:r for r in con.execute('SELECT * FROM commute_check')}
    with (out/'eligibilite.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['employee_id','nom','prenom','bu','salaire_brut','mode_deplacement','sport_declare','distance_km','statut_distance','source_distance','nb_activites_12m','prime_eligible','montant_prime_eur','bien_etre_eligible','jours_bien_etre'])
        for e in employees:
            n=counts.get(e['employee_id'],0);c=commute[e['employee_id']]
            # Without verified Google route, eligibility is explicitly UNKNOWN; never pay based on a guessed distance.
            prime=(normalize_mode(e['commute_mode'])!='other' and c['status']=='VALIDE')
            eligible=n>=config['wellbeing_activity_threshold']
            w.writerow([e['employee_id'],e['last_name'],e['first_name'],e['bu'],e['gross_salary'],e['commute_mode'],e['declared_sport'],c['distance_km'],c['status'],c['source'],n,int(prime),round(e['gross_salary']*config['prime_rate'],2) if prime else 0,int(eligible),int(config['wellbeing_days']) if eligible else 0])
    export_csv(con,out/'activites.csv','SELECT activity_id,employee_id,start_at,end_at,sport_type,distance_m,elapsed_s,comment,source FROM activity')
    export_csv(con,out/'qualite.csv','SELECT id,category,employee_id,detail FROM anomaly')
    export_csv(con,out/'monitoring.csv','SELECT * FROM pipeline_run')
    export_csv(con,out/'notifications.csv','SELECT * FROM notification')
    export_csv(con,out/'parametres.csv','SELECT * FROM config')

def execute(args):
    db=Path(args.db);db.parent.mkdir(parents=True,exist_ok=True)
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(db);con.row_factory=sqlite3.Row;con.execute('PRAGMA foreign_keys=ON');con.executescript(SCHEMA)
    for k,v in DEFAULTS.items():con.execute('INSERT OR IGNORE INTO config(key,value) VALUES(?,?)',(k,v))
    if args.prime_rate is not None:
        if not 0<=args.prime_rate<=1:raise ValueError('taux doit être compris entre 0 et 1')
        con.execute('UPDATE config SET value=? WHERE key=?',(args.prime_rate,'prime_rate'))
    if args.threshold is not None:
        if args.threshold<1:raise ValueError('seuil doit être positif')
        con.execute('UPDATE config SET value=? WHERE key=?',(args.threshold,'wellbeing_activity_threshold'))
    started=dt.datetime.now().isoformat(timespec='seconds')
    cur=con.execute("INSERT INTO pipeline_run(started_at,status) VALUES(?,'RUNNING')",(started,));run_id=cur.lastrowid;con.commit()
    try:
        employees,anomalies=load_employees(args.rh,args.sports)
        if not employees:raise ValueError('aucun salarié importé')
        activities=simulate(employees,seed=args.seed)
        con.execute('DELETE FROM notification');con.execute('DELETE FROM anomaly');con.execute('DELETE FROM commute_check');con.execute('DELETE FROM activity');con.execute('DELETE FROM employee')
        con.executemany('INSERT INTO employee VALUES(?,?,?,?,?,?,?,?)',employees)
        con.executemany('INSERT INTO anomaly(category,employee_id,detail) VALUES(?,?,?)',anomalies)
        params=dict(con.execute('SELECT key,value FROM config'))
        for e in employees:
            kind=normalize_mode(e[6]);status='NON_APPLICABLE' if kind=='other' else 'NON_VERIFIE';distance=None;source='aucune';detail='Déplacement non sportif' if kind=='other' else 'Clé Google Maps absente : éligibilité prime non confirmée'
            if kind!='other' and args.google_maps:
                try:
                    distance=google_route_distance_km(e[5],e[6],os.environ.get('GOOGLE_MAPS_API_KEY',''))
                    status='VALIDE' if commute_is_valid(e[6],distance,params) else 'A_VERIFIER';source='Google Routes API';detail='Distance calculée par itinéraire'
                except Exception as exc:
                    status='NON_VERIFIE';detail=str(exc);con.execute('INSERT INTO anomaly(category,employee_id,detail) VALUES(?,?,?)',('distance',e[0],detail))
            con.execute('INSERT INTO commute_check VALUES(?,?,?,?,?)',(e[0],distance,status,source,detail))
        con.executemany('INSERT INTO activity(employee_id,start_at,end_at,sport_type,distance_m,elapsed_s,comment,source) VALUES(?,?,?,?,?,?,?,?)',[(a['employee_id'],a['start_at'],a['end_at'],a['sport_type'],a['distance_m'],a['elapsed_s'],a['comment'],a['source']) for a in activities])
        # One illustrative new activity triggers notification; historical rows are not re-posted.
        a=activities[-1];employee=next(e for e in employees if e[0]==a['employee_id']);message=notification_message(employee,a)
        status='SIMULATION_NON_ENVOYEE'
        if args.slack:
            webhook=os.environ.get('SLACK_WEBHOOK_URL','')
            if webhook:
                try:send_slack(message,webhook);status='ENVOYEE'
                except Exception as exc:
                    status='ERREUR_ENVOI';con.execute('INSERT INTO anomaly(category,employee_id,detail) VALUES(?,?,?)',('slack',employee[0],str(exc)))
            else:status='WEBHOOK_ABSENT'
        con.execute('INSERT INTO notification(activity_id,message,status,created_at) VALUES(?,?,?,?)',(len(activities),message,status,dt.datetime.now().isoformat(timespec='seconds')))
        count=con.execute('SELECT COUNT(*) FROM anomaly').fetchone()[0]
        con.execute("UPDATE pipeline_run SET ended_at=?,status='SUCCESS',employees=?,activities=?,anomalies=? WHERE run_id=?",(dt.datetime.now().isoformat(timespec='seconds'),len(employees),len(activities),count,run_id));con.commit()
        build_exports(con,out)
        print(json.dumps({'status':'SUCCESS','employees':len(employees),'activities':len(activities),'anomalies':count,'db':str(db),'exports':str(out),'google_maps':args.google_maps,'slack':status},ensure_ascii=False,indent=2))
    except Exception as exc:
        con.rollback();con.execute("UPDATE pipeline_run SET ended_at=?,status='FAILED',error_message=? WHERE run_id=?",(dt.datetime.now().isoformat(timespec='seconds'),str(exc),run_id));con.commit();raise
    finally:con.close()

def main():
    parser=argparse.ArgumentParser(description='POC Avantages Sportifs')
    parser.add_argument('--rh',default=str(ROOT/'data/input/rh.xlsx'))
    parser.add_argument('--sports',default=str(ROOT/'data/input/sports.xlsx'))
    parser.add_argument('--db',default=str(ROOT/'data/poc_sport.sqlite'))
    parser.add_argument('--output',default=str(ROOT/'data/output'))
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--prime-rate',type=float)
    parser.add_argument('--threshold',type=int)
    parser.add_argument('--google-maps',action='store_true',help='requiert GOOGLE_MAPS_API_KEY')
    parser.add_argument('--slack',action='store_true',help='requiert SLACK_WEBHOOK_URL')
    args=parser.parse_args();execute(args)
if __name__=='__main__':main()
