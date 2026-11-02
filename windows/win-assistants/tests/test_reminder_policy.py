import unittest
from datetime import datetime
from win_assistants.reminder_policy import allows, scheduled_key, task_alert_decision, TZ


class SharedReminderPolicyTests(unittest.TestCase):
    def policy(self, **values):
        return {'enabled':True, 'instant':True, 'scheduled':True, 'times':['09:00'],
                'weekdays':[0,2,4], 'categories':{'number_inbox':True,'task':True,'task_global':True,'task_customer':True}, **values}

    def test_modes_weekdays_and_global_switch(self):
        monday = datetime(2026,11,2,9,0,tzinfo=TZ)
        self.assertEqual(scheduled_key(self.policy(),monday),'2026-11-02:09:00')
        self.assertEqual(scheduled_key(self.policy(),monday.replace(day=3)),'')
        self.assertEqual(scheduled_key(self.policy(scheduled=False),monday),'')
        self.assertEqual(scheduled_key(self.policy(enabled=False),monday),'')
        self.assertFalse(allows(self.policy(enabled=False),'task'))
        self.assertTrue(allows(None,'task'))  # Existing servers remain usable.
        self.assertFalse(allows(False,'task'))

    def test_scopes_modes_and_no_muted_backlog(self):
        seen=set(); slot=''
        item={'id':1,'title':'全局','remind_at':'2026-11-01T09:00','due':True}
        customer=dict(item,source='customer',title='客户')
        payload={'items':[item],'customer_task_reminders':[customer],'reminder_policy':self.policy(instant=False)}
        due, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,8,59,tzinfo=TZ))
        self.assertFalse(alert)
        due, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,9,0,tzinfo=TZ))
        self.assertTrue(alert)
        self.assertEqual([row['title'] for row in due],['全局','客户'])
        _, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,9,0,tzinfo=TZ))
        self.assertFalse(alert)
        payload['reminder_policy']=self.policy(enabled=False)
        due, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,9,0,tzinfo=TZ))
        self.assertEqual(due,[])
        self.assertFalse(alert)
        policy=self.policy(instant=False,times=['09:00','10:00'])
        policy['categories']['task_customer']=False
        payload['reminder_policy']=policy
        due, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,10,0,tzinfo=TZ))
        self.assertTrue(alert)
        self.assertEqual([row['title'] for row in due],['全局'])
        # Both sources keep distinct IDs; completing work clears deduplication.
        payload['items']=[];payload['customer_task_reminders']=[]
        due, alert, slot=task_alert_decision(payload,seen,slot,datetime(2026,11,2,10,0,tzinfo=TZ))
        self.assertFalse(alert)
        self.assertEqual(seen,set())


if __name__ == '__main__':
    unittest.main()
