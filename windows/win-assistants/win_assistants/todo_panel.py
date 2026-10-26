"""Independent todo module UI, hosted by the existing Windows application."""
from datetime import datetime, timedelta, timezone
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.error
from .work_todos import request_todos, api_url
from .sms import protect_secret, unprotect_secret


class TodoPanel:
    def __init__(self, app, page):
        self.app, self.page = app, page
        self.items = {}
        self.notified = set()
        self.actions = queue.Queue()
        self.busy = False
        self.popup = None
        self.show_done = tk.BooleanVar(value=False)
        toolbar = ttk.Frame(page)
        toolbar.pack(fill='x')
        ttk.Button(toolbar, text='新增', command=lambda: self.edit()).pack(side='left')
        ttk.Button(toolbar, text='编辑', command=self.edit_selected).pack(side='left')
        ttk.Button(toolbar, text='结办 / 重新打开', command=self.complete).pack(side='left')
        ttk.Button(toolbar, text='延期', command=self.postpone).pack(side='left')
        ttk.Button(toolbar, text='刷新', command=app.todo_receiver.refresh).pack(side='left')
        ttk.Checkbutton(toolbar, text='显示已结办', variable=self.show_done, command=self.render).pack(side='right')
        columns = ('title','remind','status')
        self.tree = ttk.Treeview(page, columns=columns, show='headings', height=8, selectmode='browse')
        for col,label,width in [('title','待办事项',300),('remind','提醒（北京时间）',160),('status','状态',80)]:
            self.tree.heading(col,text=label)
            self.tree.column(col,width=width,minwidth=60)
        self.tree.pack(fill='both',expand=True,pady=8)
        scroll = ttk.Scrollbar(page,orient='vertical',command=self.tree.yview)
        scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>',lambda e:self.edit_selected())

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo('待办事项','请先选择一项待办')
            return None
        return self.items.get(int(selection[0]))

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for item in self.items.values():
            if item['done'] and not self.show_done.get():
                continue
            self.tree.insert('', 'end', iid=str(item['id']),values=(item['title'],item['remind_at'].replace('T',' '),'已结办' if item['done'] else ('已到期' if item['due'] else '待处理')))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def apply(self, payload):
        self.items = {int(i['id']):i for i in payload['items']}
        self.render()
        due = [i for i in self.items.values() if i['due']]
        current = {(i['id'],i['remind_at']) for i in due}
        self.notified.intersection_update(current)
        fresh = [i for i in due if (i['id'],i['remind_at']) not in self.notified]
        if fresh:
            self.notified.update((i['id'],i['remind_at']) for i in fresh)
            self.show_due(due)
        elif self.popup is not None and self.popup.winfo_exists():
            if due:
                self.popup_text.set('\n'.join(i['title'] for i in due[:10]))
            else:
                self.popup.destroy()
                self.popup = None

    def show_due(self, due):
        if self.app.tray_icon:
            try:
                self.app.tray_icon.notify(f"{len(due)} 项待办已到提醒时间：{due[0]['title']}",'待办事项')
            except Exception:
                pass
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self.app.root)
            self.popup.title('待办事项提醒')
            self.popup.geometry('420x260')
            self.popup_text = tk.StringVar()
            ttk.Label(self.popup,textvariable=self.popup_text,wraplength=380).pack(fill='both',expand=True,padx=20,pady=15)
            ttk.Button(self.popup,text='查看并处理',command=self.open_page).pack(pady=10)
        self.popup_text.set('\n'.join(i['title'] for i in due[:10]))
        self.popup.lift()

    def open_page(self):
        self.app.navigation.select(self.page)
        self.app._show_window()
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None

    def send(self, item, payload, dialog=None):
        if self.busy:
            return
        self.busy = True
        server = self.app.config.work_todos.server_url
        try:
            token = unprotect_secret(self.app.config.work_todos.protected_token)
        except Exception as exc:
            self.busy = False
            messagebox.showerror('待办事项',str(exc))
            return
        def run():
            try:
                data = request_todos(server,token,item['id'] if item else None,payload)
                self.actions.put(('saved',data,dialog))
            except urllib.error.HTTPError as exc:
                message = '保存失败，请刷新后重试'
                try:
                    import json
                    message = json.loads(exc.read(16384)).get('detail',message)
                except Exception:
                    pass
                self.actions.put(('error',message,None))
            except Exception as exc:
                self.actions.put(('error',str(exc),None))
        threading.Thread(target=run,daemon=True).start()

    def poll(self):
        while True:
            try:
                kind,data,dialog = self.actions.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if kind == 'saved':
                if dialog is not None and dialog.winfo_exists():
                    dialog.destroy()
                # Avoid painting an older snapshot over a newer poll; fetch server truth.
                self.app.todo_receiver.refresh()
            else:
                messagebox.showerror('待办事项',data)
                self.app.todo_receiver.refresh()

    def edit_selected(self):
        item = self.selected()
        if item:
            self.edit(item)

    def edit(self,item=None):
        # Called without item only by the explicit New action.
        dialog = tk.Toplevel(self.app.root)
        dialog.title('编辑待办' if item else '新增待办')
        dialog.geometry('480x360')
        title = tk.StringVar(value=item['title'] if item else '')
        remind = tk.StringVar(value=item['remind_at'].replace('T',' ') if item else '')
        ttk.Label(dialog,text='标题').pack(anchor='w',padx=16)
        ttk.Entry(dialog,textvariable=title).pack(fill='x',padx=16)
        ttk.Label(dialog,text='提醒时间（北京时间 YYYY-MM-DD HH:MM，可留空）').pack(anchor='w',padx=16,pady=(12,0))
        ttk.Entry(dialog,textvariable=remind).pack(fill='x',padx=16)
        ttk.Label(dialog,text='备注').pack(anchor='w',padx=16,pady=(12,0))
        note = tk.Text(dialog,height=5)
        note.pack(fill='both',expand=True,padx=16)
        note.insert('1.0',item['note'] if item else '')
        def save():
            self.send(item,{'action':'edit','revision':item['revision'] if item else 0,'title':title.get(),'remind_at':remind.get().strip().replace(' ','T'),'note':note.get('1.0','end-1c')},dialog)
        ttk.Button(dialog,text='保存',command=save).pack(pady=12)

    def complete(self):
        item = self.selected()
        if item:
            self.send(item,{'action':'reopen' if item['done'] else 'done','revision':item['revision']})

    def postpone(self):
        item = self.selected()
        if not item:
            return
        dialog = tk.Toplevel(self.app.root)
        dialog.title('延期（北京时间）')
        value = tk.StringVar(value=(datetime.now(timezone(timedelta(hours=8)))+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M'))
        ttk.Label(dialog,text='延期至 YYYY-MM-DD HH:MM').pack(padx=20,pady=10)
        ttk.Entry(dialog,textvariable=value,width=28).pack(padx=20,pady=10)
        ttk.Button(dialog,text='确认延期',command=lambda:self.send(item,{'action':'postpone','revision':item['revision'],'remind_at':value.get().strip().replace(' ','T')},dialog)).pack(pady=10)

    def settings(self):
        dialog = tk.Toplevel(self.app.root)
        dialog.title('待办事项连接')
        server = tk.StringVar(value=self.app.config.work_todos.server_url)
        try:
            current = unprotect_secret(self.app.config.work_todos.protected_token)
        except Exception:
            current = ''
        token = tk.StringVar(value=current)
        ttk.Label(dialog,text='网站根地址').pack(anchor='w',padx=20,pady=(15,0))
        ttk.Entry(dialog,textvariable=server,width=48).pack(padx=20,pady=8)
        ttk.Label(dialog,text='网页版 → 工作 → 待办事项 → 客户端连接 → 连接码').pack(padx=20)
        ttk.Entry(dialog,textvariable=token,width=48,show='*').pack(padx=20,pady=8)
        def save():
            try:
                api_url(server.get())
                if not token.get().strip():
                    raise ValueError('请填写待办连接码')
                protected = protect_secret(token.get().strip())
            except Exception as exc:
                messagebox.showerror('待办事项',str(exc),parent=dialog)
                return
            self.app.config.work_todos.server_url = server.get().strip().rstrip('/')
            self.app.config.work_todos.protected_token = protected
            self.app.config.save()
            self.notified.clear()
            if self.app.enabled_vars['work_todos'].get():
                self.app._start_one('work_todos')
            dialog.destroy()
        ttk.Button(dialog,text='保存连接',command=save).pack(pady=15)
