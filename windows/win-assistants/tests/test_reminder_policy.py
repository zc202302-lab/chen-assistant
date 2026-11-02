import unittest
from datetime import datetime
from unittest.mock import patch
from types import SimpleNamespace
from win_assistants.reminder_policy import allows, scheduled_key, TZ
from win_assistants.todo_panel import TodoPanel


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

    def panel(self):
        panel = TodoPanel.__new__(TodoPanel)
        panel.items={};panel.notified=set();panel.popup=None;panel.last_schedule_key=''
        panel.render=lambda:None
        panel.alerts=[]
        panel.show_due=lambda items:panel.alerts.append([item['title'] for item in items])
        return panel

    def test_scopes_modes_and_no_muted_backlog(self):
        panel=self.panel()
        item={'id':1,'title':'全局','remind_at':'2026-11-01T09:00','due':True}
        customer=dict(item,source='customer',title='客户')
        payload={'items':[item],'customer_task_reminders':[customer],'reminder_policy':self.policy(instant=False)}
        with patch('win_assistants.todo_panel.scheduled_key',return_value=''):
            panel.apply(payload)
        self.assertEqual(panel.alerts,[])
        with patch('win_assistants.todo_panel.scheduled_key',return_value='2026-11-02:09:00'):
            panel.apply(payload);panel.apply(payload)
        self.assertEqual(panel.alerts,[['全局','客户']])
        self.assertEqual(list(panel.items),[1])
        payload['reminder_policy']=self.policy(enabled=False)
        panel.apply(payload)
        self.assertEqual(len(panel.alerts),1)
        # Category scope removal also applies to timed reminders.
        policy=self.policy(instant=False)
        policy['categories']['task_customer']=False
        payload['reminder_policy']=policy
        with patch('win_assistants.todo_panel.scheduled_key',return_value='2026-11-02:10:00'):
            panel.apply(payload)
        self.assertEqual(panel.alerts[-1],['全局'])


if __name__ == '__main__':
    unittest.main()
