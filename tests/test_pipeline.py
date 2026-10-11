import datetime as dt,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from pipeline import validate_activity,commute_is_valid,normalize_mode,simulate,notification_message
class TestPOC(unittest.TestCase):
 def test_modes(self):
  self.assertEqual(normalize_mode('Vélo'),'bike');self.assertEqual(normalize_mode('Marche à pied'),'walk');self.assertEqual(normalize_mode('Transports en commun'),'other')
 def test_distances(self):
  self.assertTrue(commute_is_valid('Marche',15));self.assertFalse(commute_is_valid('Marche',15.01));self.assertTrue(commute_is_valid('Vélo',25));self.assertFalse(commute_is_valid('Vélo',26));self.assertIsNone(commute_is_valid('Bus',2))
 def test_activity_validation(self):
  a={'elapsed_s':60,'distance_m':None,'start_at':'2026-01-01','end_at':'2026-01-02','sport_type':'Yoga'};validate_activity(a)
  a['distance_m']=-1
  with self.assertRaises(ValueError):validate_activity(a)
 def test_simulation(self):
  people=[(123,'Test','Marie','RH',30000,'','Vélo','Tennis')]
  a=simulate(people);self.assertGreater(len(a),0);self.assertTrue(all(x['employee_id']==123 for x in a))
 def test_notification(self):
  p=(1,'Test','Marie','RH',1,'','','');a={'sport_type':'Course','distance_m':5000,'elapsed_s':1800}
  self.assertIn('5.0 km',notification_message(p,a))
if __name__=='__main__':unittest.main()
