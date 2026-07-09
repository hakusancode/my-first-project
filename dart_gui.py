import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from dart_engine import (calculate_financial_ratios, download_document, get_audit_opinion_3y,
    get_capital_changes, get_dividend_info_3y, get_employee_status, get_equity_investments,
    get_extended_financials_3y, get_key_financials_3y, get_major_shareholder, list_disclosures,
    load_corp_list, search_company)

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DOWNLOADS = os.path.join(_HERE, 'downloads')

_FIN_LABELS = ['매출액', '영업이익', '당기순이익', '자산총계', '부채총계', '자본총계']
_DIV_LABELS = ['주당배당금(원)', '배당성향(%)', '시가배당률(%)', '현금배당총액(백만원)']
_RATIO_LABELS = ['영업이익률', '순이익률', '부채비율', 'ROE', 'ROA', '매출총이익률', '매출원가율', '총포괄이익률']

_ANALYSIS_TABS = ['핵심재무', '배당', '타법인출자', '재무지표', '감사', '최대주주', '직원', '자본변동']


def _fmt_val(val):
    '''금액 포맷 + 색상. (표시문자열, 텍스트 색상) 반환.'''
    if val is None:
        return ('N/A', 'gray50')
    trillion = 1000000000000
    billion = 100000000
    abs_val = abs(val)
    if abs_val >= trillion:
        s = f'{abs_val / trillion:.2f}조'
    elif abs_val >= billion:
        s = f'{abs_val / billion:.0f}억'
    else:
        s = f'{abs_val:,}원'
    if val < 0:
        return (f'-{s}', '#FF6B6B')
    return (s, 'white')


def _fmt_div_val(val, key):
    '''배당 항목별 포맷 + 색상. (표시문자열, 텍스트 색상) 반환.'''
    if val is None:
        return ('N/A', 'gray50')
    if '%' in key:
        color = '#FF6B6B' if val < 0 else 'white'
        return (f'{val:.2f}%', color)
    if '백만원' in key:
        return _fmt_val(int(val) * 1000000)
    return (f'{int(val):,}원', 'white')


def _fmt_ratio_val(val):
    '''재무비율 포맷 + 색상. (표시문자열, 텍스트 색상) 반환.'''
    if val is None:
        return ('N/A', 'gray50')
    color = '#FF6B6B' if val < 0 else 'white'
    return (f'{val:.2f}%', color)


class DartApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title('DART 공시 다운로더')
        self.geometry('1300x720')
        self.minsize(1000, 580)

        self.corp_list = None
        self._search_results = []
        self.selected_corp = None
        self._fin_data = None

        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(self)
        left.grid(row=0, column=0, sticky='nsew', padx=(12, 4), pady=12)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        self._build_top(left)
        self._build_mid(left)
        self._build_log(left)
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky='nsew', padx=(4, 12), pady=12)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        self._build_analysis(right)

    def _build_top(self, parent):
        f = ctk.CTkFrame(parent)
        f.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 4))
        f.grid_columnconfigure(1, weight=1)
        f.grid_columnconfigure(3, weight=2)
        ctk.CTkLabel(f, text='인증키').grid(row=0, column=0, padx=(10, 6), pady=8, sticky='w')
        self.api_key_var = tk.StringVar(value='')
        ctk.CTkEntry(f, textvariable=self.api_key_var, placeholder_text='DART Open API 인증키 입력').grid(row=0, column=1, padx=4, pady=8, sticky='ew')
        ctk.CTkLabel(f, text='저장폴더').grid(row=0, column=2, padx=(12, 6), pady=8, sticky='w')
        self.save_dir_var = tk.StringVar(value=_DEFAULT_DOWNLOADS)
        ctk.CTkEntry(f, textvariable=self.save_dir_var).grid(row=0, column=3, padx=4, pady=8, sticky='ew')
        ctk.CTkButton(f, text='찾아보기', width=80, command=self._browse_dir).grid(row=0, column=4, padx=(4, 10), pady=8)

    def _build_mid(self, parent):
        f = ctk.CTkFrame(parent)
        f.grid(row=1, column=0, sticky='ew', padx=8, pady=4)
        f.grid_columnconfigure(0, weight=1)
        self._build_search(f)
        self._build_options(f)

    def _build_search(self, parent):
        f = ctk.CTkFrame(parent)
        f.grid(row=0, column=0, sticky='nsew', padx=(8, 4), pady=8)
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text='회사 검색', font=ctk.CTkFont(size=13, weight='bold')).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 6), sticky='w')
        row = ctk.CTkFrame(f, fg_color='transparent')
        row.grid(row=1, column=0, columnspan=2, sticky='ew', padx=10)
        row.grid_columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        entry = ctk.CTkEntry(row, textvariable=self.search_var, placeholder_text='회사명 입력 후 엔터')
        entry.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        entry.bind('<Return>', lambda _: self._do_search())
        ctk.CTkButton(row, text='검색', width=64, command=self._do_search).grid(row=0, column=1)
        lb_wrap = ctk.CTkFrame(f, fg_color='transparent')
        lb_wrap.grid(row=2, column=0, columnspan=2, sticky='ew', padx=10, pady=(8, 0))
        self.listbox = tk.Listbox(lb_wrap, height=6, selectmode=tk.SINGLE, bg='#2b2b2b', fg='white', selectbackground='#1f6aa5', activestyle='none', relief='flat', borderwidth=0, font=('Consolas', 10), exportselection=False)
        sb = tk.Scrollbar(lb_wrap, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.selected_label = ctk.CTkLabel(f, text='선택된 회사: 없음', text_color='gray')
        self.selected_label.grid(row=3, column=0, columnspan=2, padx=10, pady=(6, 10), sticky='w')

    def _build_options(self, parent):
        f = ctk.CTkFrame(parent)
        f.grid(row=0, column=1, sticky='ns', padx=(4, 8), pady=8)
        ctk.CTkLabel(f, text='조회 옵션', font=ctk.CTkFont(size=13, weight='bold')).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 8), sticky='w')
        ctk.CTkLabel(f, text='시작연도').grid(row=1, column=0, padx=(12, 6), pady=4, sticky='w')
        self.bgn_year_var = tk.StringVar(value='2021')
        ctk.CTkEntry(f, textvariable=self.bgn_year_var, width=78).grid(row=1, column=1, padx=(0, 12), pady=4, sticky='w')
        ctk.CTkLabel(f, text='종료연도').grid(row=2, column=0, padx=(12, 6), pady=4, sticky='w')
        self.end_year_var = tk.StringVar(value='2026')
        ctk.CTkEntry(f, textvariable=self.end_year_var, width=78).grid(row=2, column=1, padx=(0, 12), pady=4, sticky='w')
        ctk.CTkLabel(f, text='보고서 유형').grid(row=3, column=0, columnspan=2, padx=12, pady=(10, 4), sticky='w')
        self.chk_annual = tk.BooleanVar(value=True)
        self.chk_semi = tk.BooleanVar(value=True)
        self.chk_quarter = tk.BooleanVar(value=True)
        for i, (text, var) in enumerate([('사업보고서', self.chk_annual), ('반기보고서', self.chk_semi), ('분기보고서', self.chk_quarter)], start=4):
            ctk.CTkCheckBox(f, text=text, variable=var).grid(row=i, column=0, columnspan=2, padx=12, pady=3, sticky='w')
        self.download_btn = ctk.CTkButton(f, text='다운로드', height=38, command=self._do_download)
        self.download_btn.grid(row=7, column=0, columnspan=2, padx=12, pady=(14, 12), sticky='ew')

    def _build_log(self, parent):
        f = ctk.CTkFrame(parent)
        f.grid(row=2, column=0, sticky='nsew', padx=8, pady=(4, 8))
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(f, text='로그', font=ctk.CTkFont(size=13, weight='bold')).grid(row=0, column=0, padx=10, pady=(8, 0), sticky='w')
        self.log_box = ctk.CTkTextbox(f, state='disabled', font=('Consolas', 10), wrap='word')
        self.log_box.grid(row=1, column=0, sticky='nsew', padx=10, pady=(4, 10))

    def _build_analysis(self, parent):
        tabview = ctk.CTkTabview(parent)
        tabview.grid(row=0, column=0, sticky='nsew', padx=8, pady=8)
        for name in _ANALYSIS_TABS:
            tabview.add(name)
        fin_tab = tabview.tab('핵심재무')
        fin_tab.grid_columnconfigure(0, weight=1)
        fin_tab.grid_rowconfigure(1, weight=1)
        self._fin_title = ctk.CTkLabel(fin_tab, text='기업분석 — 핵심재무', font=ctk.CTkFont(size=13, weight='bold'))
        self._fin_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._fin_content = ctk.CTkFrame(fin_tab, fg_color='transparent')
        self._fin_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._fin_content.grid_columnconfigure(0, weight=1)
        self._fin_content.grid_rowconfigure(0, weight=1)
        self._render_fin('initial')
        div_tab = tabview.tab('배당')
        div_tab.grid_columnconfigure(0, weight=1)
        div_tab.grid_rowconfigure(1, weight=1)
        self._div_title = ctk.CTkLabel(div_tab, text='기업분석 — 배당', font=ctk.CTkFont(size=13, weight='bold'))
        self._div_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._div_content = ctk.CTkFrame(div_tab, fg_color='transparent')
        self._div_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._div_content.grid_columnconfigure(0, weight=1)
        self._div_content.grid_rowconfigure(0, weight=1)
        self._render_div('initial')
        eqt_tab = tabview.tab('타법인출자')
        eqt_tab.grid_columnconfigure(0, weight=1)
        eqt_tab.grid_rowconfigure(1, weight=1)
        self._eqt_title = ctk.CTkLabel(eqt_tab, text='기업분석 — 타법인출자', font=ctk.CTkFont(size=13, weight='bold'))
        self._eqt_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._eqt_content = ctk.CTkFrame(eqt_tab, fg_color='transparent')
        self._eqt_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._eqt_content.grid_columnconfigure(0, weight=1)
        self._eqt_content.grid_rowconfigure(0, weight=1)
        self._render_equity('initial')
        ratio_tab = tabview.tab('재무지표')
        ratio_tab.grid_columnconfigure(0, weight=1)
        ratio_tab.grid_rowconfigure(1, weight=1)
        self._ratio_title = ctk.CTkLabel(ratio_tab, text='기업분석 — 재무지표', font=ctk.CTkFont(size=13, weight='bold'))
        self._ratio_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._ratio_content = ctk.CTkFrame(ratio_tab, fg_color='transparent')
        self._ratio_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._ratio_content.grid_columnconfigure(0, weight=1)
        self._ratio_content.grid_rowconfigure(0, weight=1)
        self._render_ratio('initial')
        adt_tab = tabview.tab('감사')
        adt_tab.grid_columnconfigure(0, weight=1)
        adt_tab.grid_rowconfigure(1, weight=1)
        self._adt_title = ctk.CTkLabel(adt_tab, text='기업분석 — 감사', font=ctk.CTkFont(size=13, weight='bold'))
        self._adt_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._adt_content = ctk.CTkScrollableFrame(adt_tab, fg_color='transparent')
        self._adt_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._adt_content.grid_columnconfigure(0, weight=1)
        self._render_audit('initial')
        shr_tab = tabview.tab('최대주주')
        shr_tab.grid_columnconfigure(0, weight=1)
        shr_tab.grid_rowconfigure(1, weight=1)
        self._shr_title = ctk.CTkLabel(shr_tab, text='기업분석 — 최대주주', font=ctk.CTkFont(size=13, weight='bold'))
        self._shr_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._shr_content = ctk.CTkScrollableFrame(shr_tab, fg_color='transparent')
        self._shr_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._shr_content.grid_columnconfigure(0, weight=1)
        self._render_shareholder('initial')
        emp_tab = tabview.tab('직원')
        emp_tab.grid_columnconfigure(0, weight=1)
        emp_tab.grid_rowconfigure(1, weight=1)
        self._emp_title = ctk.CTkLabel(emp_tab, text='기업분석 — 직원', font=ctk.CTkFont(size=13, weight='bold'))
        self._emp_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._emp_content = ctk.CTkFrame(emp_tab, fg_color='transparent')
        self._emp_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._emp_content.grid_columnconfigure(0, weight=1)
        self._emp_content.grid_rowconfigure(0, weight=1)
        self._render_employee('initial')
        cap_tab = tabview.tab('자본변동')
        cap_tab.grid_columnconfigure(0, weight=1)
        cap_tab.grid_rowconfigure(1, weight=1)
        self._cap_title = ctk.CTkLabel(cap_tab, text='기업분석 — 자본변동', font=ctk.CTkFont(size=13, weight='bold'))
        self._cap_title.grid(row=0, column=0, padx=12, pady=(10, 4), sticky='w')
        self._cap_content = ctk.CTkScrollableFrame(cap_tab, fg_color='transparent')
        self._cap_content.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._cap_content.grid_columnconfigure(0, weight=1)
        self._render_capital('initial')

    def _render_fin(self, state, data=None, corp_name='', years=None):
        "핵심재무 탭 컨텐츠를 갱신한다. state: 'initial'|'loading'|'done'|'error'"
        for w in self._fin_content.winfo_children():
            w.destroy()
        if state == 'initial':
            ctk.CTkLabel(self._fin_content, text='회사를 선택하면 재무 데이터가 표시됩니다.', text_color='gray').grid(row=0, column=0)
            return
        if state == 'loading':
            ctk.CTkLabel(self._fin_content, text='불러오는 중...', text_color='gray').grid(row=0, column=0)
            return
        if state == 'error':
            ctk.CTkLabel(self._fin_content, text='데이터를 불러오지 못했습니다.', text_color='#FF6B6B').grid(row=0, column=0)
            return
        all_none = all(row.get(label) is None for row in data for label in _FIN_LABELS)
        outer = ctk.CTkFrame(self._fin_content, fg_color='transparent')
        outer.grid(row=0, column=0, sticky='n', padx=8, pady=8)
        if all_none:
            ctk.CTkLabel(outer, text='이 회사는 XBRL 재무데이터를 지원하지 않습니다 (비상장 외감법인 등)', text_color='#FFA040').grid(row=0, column=0, pady=(0, 10), sticky='w')
        f = ctk.CTkFrame(outer, fg_color='transparent')
        f.grid(row=1, column=0, sticky='n')
        col_w = 110
        row_h = 32
        ctk.CTkLabel(f, text='항목', font=ctk.CTkFont(weight='bold'), width=120, anchor='w').grid(row=0, column=0, padx=(0, 8), pady=4, sticky='w')
        for ci, yr in enumerate(years):
            ctk.CTkLabel(f, text=f'{yr}년', font=ctk.CTkFont(weight='bold'), width=col_w, anchor='e').grid(row=0, column=ci + 1, padx=4, pady=4)
        sep = ctk.CTkFrame(f, height=1, fg_color='gray40')
        sep.grid(row=1, column=0, columnspan=len(years) + 1, sticky='ew', pady=2)
        for ri, label in enumerate(_FIN_LABELS):
            if label == '자산총계':
                sep2 = ctk.CTkFrame(f, height=1, fg_color='gray30')
                sep2.grid(row=ri * 2 + 2, column=0, columnspan=len(years) + 1, sticky='ew', pady=2)
            row_idx = ri * 2 + 3 if label != '매출액' else ri * 2 + 2
            ctk.CTkLabel(f, text=label, width=120, anchor='w').grid(row=ri + 2, column=0, padx=(0, 8), pady=6, sticky='w')
            for ci, row_data in enumerate(data):
                val = row_data.get(label)
                text, color = _fmt_val(val)
                ctk.CTkLabel(f, text=text, text_color=color, width=col_w, anchor='e').grid(row=ri + 2, column=ci + 1, padx=4, pady=6)

    def _browse_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if path:
            self.save_dir_var.set(path)

    def _log(self, msg):
        def _upd():
            ts = datetime.now().strftime('%H:%M:%S')
            self.log_box.configure(state='normal')
            self.log_box.insert('end', f'[{ts}] {msg}\n')
            self.log_box.see('end')
            self.log_box.configure(state='disabled')
        self.after(0, _upd)

    def _do_search(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            return

        def run():
            api_key = self.api_key_var.get().strip()
            if self.corp_list is None:
                try:
                    self.corp_list = load_corp_list(api_key, log_fn=self._log)
                except Exception as e:
                    self._log(f'오류: {e}')
                    return
            results = search_company(self.corp_list, keyword)
            self._log(f"'{keyword}' 검색 결과: {len(results)}건")
            self.after(0, lambda: self._fill_listbox(results))

        threading.Thread(target=run, daemon=True).start()

    def _fill_listbox(self, results):
        self._search_results = results
        self.listbox.delete(0, tk.END)
        for r in results:
            self.listbox.insert(tk.END, f'  {r["corp_code"]}  {r["corp_name"]}')

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.selected_corp = self._search_results[sel[0]]
        name = self.selected_corp['corp_name']
        code = self.selected_corp['corp_code']
        self.selected_label.configure(text=f'선택된 회사: {name}  ({code})', text_color='white')
        self._fin_title.configure(text=f'{name} — 핵심재무')
        self._div_title.configure(text=f'{name} — 배당')
        self._eqt_title.configure(text=f'{name} — 타법인출자')
        self._ratio_title.configure(text=f'{name} — 재무지표')
        self._adt_title.configure(text=f'{name} — 감사')
        self._shr_title.configure(text=f'{name} — 최대주주')
        self._emp_title.configure(text=f'{name} — 직원')
        self._cap_title.configure(text=f'{name} — 자본변동')
        self._load_financials()
        self._load_dividends()
        self._load_equity()
        self._load_audit()
        self._load_shareholder()
        self._load_employee()
        self._load_capital()

    def _load_financials(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)

        self.after(0, lambda: self._render_fin('loading'))
        self.after(0, lambda: self._render_ratio('loading'))

        def run():
            try:
                data = get_key_financials_3y(api_key, corp['corp_code'], end_year, log_fn=self._log)
                years = [r['year'] for r in data]
                try:
                    ext = get_extended_financials_3y(api_key, corp['corp_code'], end_year, log_fn=self._log)
                except Exception as e:
                    self._log(f'확장재무 조회 실패 (무시): {e}')
                    ext = None
                ratios = calculate_financial_ratios(data, extended_3y=ext)
                self._fin_data = data
                self.after(0, lambda: self._render_fin('done', data=data, corp_name=corp['corp_name'], years=years))
                self.after(0, lambda: self._render_ratio('done', data=ratios, years=years))
            except Exception as e:
                self._log(f'재무 데이터 오류: {e}')
                self.after(0, lambda: self._render_fin('error'))
                self.after(0, lambda: self._render_ratio('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_div(self, state, data=None, years=None):
        "배당 탭 컨텐츠를 갱신한다. state: 'initial'|'loading'|'done'|'error'"
        for w in self._div_content.winfo_children():
            w.destroy()
        if state == 'initial':
            ctk.CTkLabel(self._div_content, text='회사를 선택하면 배당 데이터가 표시됩니다.', text_color='gray').grid(row=0, column=0)
            return
        if state == 'loading':
            ctk.CTkLabel(self._div_content, text='불러오는 중...', text_color='gray').grid(row=0, column=0)
            return
        if state == 'error':
            ctk.CTkLabel(self._div_content, text='데이터를 불러오지 못했습니다.', text_color='#FF6B6B').grid(row=0, column=0)
            return
        f = ctk.CTkFrame(self._div_content, fg_color='transparent')
        f.grid(row=0, column=0, sticky='n', padx=8, pady=8)
        col_w = 130
        ctk.CTkLabel(f, text='항목', font=ctk.CTkFont(weight='bold'), width=160, anchor='w').grid(row=0, column=0, padx=(0, 8), pady=4, sticky='w')
        for ci, yr in enumerate(years):
            ctk.CTkLabel(f, text=f'{yr}년', font=ctk.CTkFont(weight='bold'), width=col_w, anchor='e').grid(row=0, column=ci + 1, padx=4, pady=4)
        sep = ctk.CTkFrame(f, height=1, fg_color='gray40')
        sep.grid(row=1, column=0, columnspan=len(years) + 1, sticky='ew', pady=2)
        for ri, label in enumerate(_DIV_LABELS):
            ctk.CTkLabel(f, text=label, width=160, anchor='w').grid(row=ri + 2, column=0, padx=(0, 8), pady=6, sticky='w')
            for ci, row_data in enumerate(data):
                val = row_data.get(label)
                text, color = _fmt_div_val(val, label)
                ctk.CTkLabel(f, text=text, text_color=color, width=col_w, anchor='e').grid(row=ri + 2, column=ci + 1, padx=4, pady=6)

    def _load_dividends(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)

        self.after(0, lambda: self._render_div('loading'))

        def run():
            try:
                data = get_dividend_info_3y(api_key, corp['corp_code'], end_year, log_fn=self._log)
                years = [r['year'] for r in data]
                self.after(0, lambda: self._render_div('done', data=data, years=years))
            except Exception as e:
                self._log(f'배당 데이터 오류: {e}')
                self.after(0, lambda: self._render_div('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_ratio(self, state, data=None, years=None):
        "재무지표 탭 컨텐츠 갱신. state: 'initial'|'loading'|'done'|'error'"
        for w in self._ratio_content.winfo_children():
            w.destroy()
        msgs = {'initial': ('회사를 선택하면 재무지표가 표시됩니다.', 'gray'),
                'loading': ('불러오는 중...', 'gray'),
                'error': ('데이터를 불러오지 못했습니다.', '#FF6B6B')}
        if state in msgs:
            text, color = msgs[state]
            ctk.CTkLabel(self._ratio_content, text=text, text_color=color).grid(row=0, column=0)
            return
        f = ctk.CTkFrame(self._ratio_content, fg_color='transparent')
        f.grid(row=0, column=0, sticky='n', padx=8, pady=8)
        col_w = 110
        ctk.CTkLabel(f, text='항목', font=ctk.CTkFont(weight='bold'), width=120, anchor='w').grid(row=0, column=0, padx=(0, 8), pady=4, sticky='w')
        for ci, yr in enumerate(years):
            ctk.CTkLabel(f, text=f'{yr}년', font=ctk.CTkFont(weight='bold'), width=col_w, anchor='e').grid(row=0, column=ci + 1, padx=4, pady=4)
        sep = ctk.CTkFrame(f, height=1, fg_color='gray40')
        sep.grid(row=1, column=0, columnspan=len(years) + 1, sticky='ew', pady=2)
        for ri, label in enumerate(_RATIO_LABELS):
            if label in ('부채비율', '매출총이익률'):
                ctk.CTkFrame(f, height=1, fg_color='gray30').grid(row=ri + 2, column=0, columnspan=len(years) + 1, sticky='ew', pady=2)
            ctk.CTkLabel(f, text=label, width=120, anchor='w').grid(row=ri + 2, column=0, padx=(0, 8), pady=6, sticky='w')
            for ci, row_data in enumerate(data):
                val = row_data.get(label)
                text, color = _fmt_ratio_val(val)
                ctk.CTkLabel(f, text=text, text_color=color, width=col_w, anchor='e').grid(row=ri + 2, column=ci + 1, padx=4, pady=6)

    def _render_equity(self, state, data=None, year=None, corp_name=''):
        "타법인출자 탭 컨텐츠 갱신. state: 'initial'|'loading'|'done'|'error'"
        for w in self._eqt_content.winfo_children():
            w.destroy()
        if state == 'initial':
            ctk.CTkLabel(self._eqt_content, text='회사를 선택하면 출자 현황이 표시됩니다.', text_color='gray').grid(row=0, column=0)
            return
        if state == 'loading':
            ctk.CTkLabel(self._eqt_content, text='불러오는 중...', text_color='gray').grid(row=0, column=0)
            return
        if state == 'error':
            ctk.CTkLabel(self._eqt_content, text='데이터를 불러오지 못했습니다.', text_color='#FF6B6B').grid(row=0, column=0)
            return
        if not data:
            ctk.CTkLabel(self._eqt_content, text='출자 내역이 없습니다.', text_color='gray').grid(row=0, column=0)
            return
        info_frame = ctk.CTkFrame(self._eqt_content, fg_color='transparent')
        info_frame.grid(row=0, column=0, sticky='ew', padx=8, pady=(4, 0))
        ctk.CTkLabel(info_frame, text=f'총 {len(data)}건  ({year}년 기준)', text_color='gray70').pack(side='left')
        scroll = ctk.CTkScrollableFrame(self._eqt_content)
        scroll.grid(row=1, column=0, sticky='nsew', padx=4, pady=4)
        self._eqt_content.grid_rowconfigure(1, weight=1)
        COL_W = [200, 105, 72, 115]
        HEADERS = ['법인명', '최초취득일', '지분율', '기말장부가액']
        for ci, (h, w) in enumerate(zip(HEADERS, COL_W)):
            anchor = 'w' if ci == 0 else 'e'
            ctk.CTkLabel(scroll, text=h, font=ctk.CTkFont(weight='bold'), width=w, anchor=anchor).grid(row=0, column=ci, padx=(0 if ci else 4, 4), pady=4, sticky=anchor)
        sep = ctk.CTkFrame(scroll, height=1, fg_color='gray40')
        sep.grid(row=1, column=0, columnspan=4, sticky='ew', pady=2)

        def _pct_color(pct):
            if pct is None:
                return 'gray50'
            if pct >= 50:
                return '#63B3ED'
            if pct >= 20:
                return '#68D391'
            return 'gray70'

        for ri, row in enumerate(data):
            pct = row['지분율']
            bv = row['기말장부가액']
            pct_s = f'{pct:.1f}%' if pct is not None else 'N/A'
            bv_s, bv_c = _fmt_val(bv) if bv is not None else ('N/A', 'gray50')
            row_idx = ri + 2
            cells = [(row['법인명'], 'w', 'white'),
                     (row['최초취득일'], 'e', 'gray70'),
                     (pct_s, 'e', _pct_color(pct)),
                     (bv_s, 'e', bv_c)]
            for ci, (text, anchor, color) in enumerate(cells):
                ctk.CTkLabel(scroll, text=text, text_color=color, width=COL_W[ci], anchor=anchor).grid(row=row_idx, column=ci, padx=(0 if ci else 4, 4), pady=2, sticky=anchor)

    def _load_equity(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)
        self.after(0, lambda: self._render_equity('loading'))

        def run():
            try:
                data = get_equity_investments(api_key, corp['corp_code'], end_year, log_fn=self._log)
                self.after(0, lambda: self._render_equity('done', data=data, year=end_year, corp_name=corp['corp_name']))
            except Exception as e:
                self._log(f'타법인출자 오류: {e}')
                self.after(0, lambda: self._render_equity('error'))

        threading.Thread(target=run, daemon=True).start()

    def _load_audit(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)
        self.after(0, lambda: self._render_audit('loading'))

        def run():
            try:
                data = get_audit_opinion_3y(api_key, corp['corp_code'], end_year, log_fn=self._log)
                self.after(0, lambda: self._render_audit('done', data=data))
            except Exception as e:
                self._log(f'감사의견 오류: {e}')
                self.after(0, lambda: self._render_audit('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_audit(self, state, data=None):
        for w in self._adt_content.winfo_children():
            w.destroy()
        msgs = {
            'initial': ('회사를 선택하면 감사 정보가 표시됩니다.', 'gray'),
            'loading': ('불러오는 중...', 'gray'),
            'error': ('데이터를 가져오지 못했습니다.', '#e05252'),
        }
        if state in msgs:
            text, color = msgs[state]
            ctk.CTkLabel(self._adt_content, text=text, text_color=color).grid(row=0, column=0, padx=8, pady=8, sticky='w')
            return
        bold = ctk.CTkFont(weight='bold')
        for ri, row in enumerate(data):
            yr = row['year']
            ctk.CTkLabel(self._adt_content, text=f'■ {yr}년도', font=bold, text_color='white').grid(row=ri * 6, column=0, padx=8, pady=(12 if ri else 4, 2), sticky='w')
            opinion_color = 'white' if '적정' in row['감사의견'] else '#e05252'
            ctk.CTkLabel(self._adt_content, text=f"감사인: {row['감사인']}   |   감사의견: {row['감사의견']}", text_color=opinion_color).grid(row=ri * 6 + 1, column=0, padx=16, pady=2, sticky='w')
            ctk.CTkLabel(self._adt_content, text='▸ 강조사항', text_color='gray70').grid(row=ri * 6 + 2, column=0, padx=16, pady=(6, 0), sticky='w')
            ctk.CTkTextbox(self._adt_content, height=50, wrap='word', fg_color='#2a2a2a', border_width=0).grid(row=ri * 6 + 3, column=0, padx=24, pady=(0, 4), sticky='ew')
            tb_emp = self._adt_content.grid_slaves(row=ri * 6 + 3, column=0)[0]
            tb_emp.insert('end', row['강조사항'])
            tb_emp.configure(state='disabled')
            ctk.CTkLabel(self._adt_content, text='▸ 핵심감사사항', text_color='gray70').grid(row=ri * 6 + 4, column=0, padx=16, pady=(6, 0), sticky='w')
            tb_core = ctk.CTkTextbox(self._adt_content, height=110, wrap='word', fg_color='#2a2a2a', border_width=0)
            tb_core.grid(row=ri * 6 + 5, column=0, padx=24, pady=(0, 4), sticky='ew')
            tb_core.insert('end', row['핵심감사사항'])
            tb_core.configure(state='disabled')
        self._adt_content.grid_columnconfigure(0, weight=1)

    def _load_shareholder(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)
        self.after(0, lambda: self._render_shareholder('loading'))

        def run():
            try:
                data = get_major_shareholder(api_key, corp['corp_code'], end_year, log_fn=self._log)
                self.after(0, lambda: self._render_shareholder('done', data=data, year=end_year))
            except Exception as e:
                self._log(f'최대주주 오류: {e}')
                self.after(0, lambda: self._render_shareholder('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_shareholder(self, state, data=None, year=None):
        for w in self._shr_content.winfo_children():
            w.destroy()
        msgs = {
            'initial': ('회사를 선택하면 최대주주 정보가 표시됩니다.', 'gray'),
            'loading': ('불러오는 중...', 'gray'),
            'error': ('데이터를 가져오지 못했습니다.', '#e05252'),
        }
        if state in msgs:
            text, color = msgs[state]
            ctk.CTkLabel(self._shr_content, text=text, text_color=color).grid(row=0, column=0, padx=8, pady=8, sticky='w')
            return
        if not data:
            ctk.CTkLabel(self._shr_content, text='최대주주 정보 없음', text_color='gray').grid(row=0, column=0, padx=8, pady=8)
            return
        f = ctk.CTkFrame(self._shr_content, fg_color='transparent')
        f.grid(row=0, column=0, sticky='nw', padx=8, pady=8)
        bold = ctk.CTkFont(weight='bold')
        headers = [('주주명', 180, 'w'), ('관계', 100, 'w'), ('주식종류', 90, 'w'), ('기말주식수', 130, 'e'), ('지분율(%)', 90, 'e')]
        for ci, (h, w, anchor) in enumerate(headers):
            ctk.CTkLabel(f, text=h, font=bold, width=w, anchor=anchor).grid(row=0, column=ci, padx=4, pady=4)
        ctk.CTkFrame(f, height=1, fg_color='gray40').grid(row=1, column=0, columnspan=len(headers), sticky='ew', pady=2)
        anchors = ['w', 'w', 'w', 'e', 'e']
        widths = [180, 100, 90, 130, 90]
        grid_row = 2
        prev_is_detail = False
        for row in data:
            is_total = row['주주명'] == '계'
            if is_total and prev_is_detail:
                ctk.CTkFrame(f, height=1, fg_color='gray30').grid(row=grid_row, column=0, columnspan=len(headers), sticky='ew', pady=2)
                grid_row += 1
            color = 'white' if row['관계'] == '최대주주' else ('gray50' if is_total else 'gray80')
            vals = [
                row['주주명'],
                row['관계'],
                row['주식종류'],
                f"{row['기말주식수']:,}" if row['기말주식수'] is not None else '-',
                f"{row['지분율']:.2f}%" if row['지분율'] is not None else '-',
            ]
            for ci, (val, anc, wd) in enumerate(zip(vals, anchors, widths)):
                ctk.CTkLabel(f, text=val, text_color=color, width=wd, anchor=anc).grid(row=grid_row, column=ci, padx=4, pady=3)
            prev_is_detail = not is_total
            grid_row += 1

    def _load_employee(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)
        self.after(0, lambda: self._render_employee('loading'))

        def run():
            try:
                data = get_employee_status(api_key, corp['corp_code'], end_year, log_fn=self._log)
                self.after(0, lambda: self._render_employee('done', data=data, year=end_year))
            except Exception as e:
                self._log(f'직원 현황 오류: {e}')
                self.after(0, lambda: self._render_employee('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_employee(self, state, data=None, year=None):
        for w in self._emp_content.winfo_children():
            w.destroy()
        msgs = {
            'initial': ('회사를 선택하면 직원 정보가 표시됩니다.', 'gray'),
            'loading': ('불러오는 중...', 'gray'),
            'error': ('데이터를 가져오지 못했습니다.', '#e05252'),
        }
        if state in msgs:
            text, color = msgs[state]
            ctk.CTkLabel(self._emp_content, text=text, text_color=color).grid(row=0, column=0, padx=8, pady=8)
            return
        f = ctk.CTkFrame(self._emp_content, fg_color='transparent')
        f.grid(row=0, column=0, sticky='n', padx=8, pady=8)
        bold = ctk.CTkFont(weight='bold')
        label_w, val_w = 160, 140

        def _row(parent, r, label, vals):
            ctk.CTkLabel(parent, text=label, width=label_w, anchor='w').grid(row=r, column=0, padx=(0, 12), pady=6, sticky='w')
            for ci, (txt, color) in enumerate(vals):
                ctk.CTkLabel(parent, text=txt, text_color=color, width=val_w, anchor='e').grid(row=r, column=ci + 1, padx=4, pady=6)

        ctk.CTkLabel(f, text='항목', font=bold, width=label_w, anchor='w').grid(row=0, column=0, padx=(0, 12), pady=4)
        gender_names = [g['성별'] for g in data['성별']]
        for ci, g in enumerate(gender_names):
            ctk.CTkLabel(f, text=g, font=bold, width=val_w, anchor='e').grid(row=0, column=ci + 1, padx=4, pady=4)
        ctk.CTkLabel(f, text='합계', font=bold, width=val_w, anchor='e').grid(row=0, column=len(gender_names) + 1, padx=4, pady=4)
        ctk.CTkFrame(f, height=1, fg_color='gray40').grid(row=1, column=0, columnspan=len(gender_names) + 2, sticky='ew', pady=2)

        def _fmt_int(v):
            if v is not None:
                return (f'{v:,}명', 'white')
            return ('-', 'gray50')

        def _fmt_tenure(v):
            if v is not None:
                return (f'{v}년', 'white')
            return ('-', 'gray50')

        def _fmt_salary(v):
            if v is None:
                return ('-', 'gray50')
            if v >= 100000000:
                return (f'{v / 100000000:.1f}억원', 'white')
            return (f'{v:,}원', 'white')

        gd = data['성별']
        _row(f, 2, '총직원수', [_fmt_int(g['직원수']) for g in gd] + [_fmt_int(data['총직원'])])
        _row(f, 3, '정규직', [_fmt_int(g['정규직']) for g in gd] + [_fmt_int(data['정규직'])])
        _row(f, 4, '계약직', [_fmt_int(g['계약직']) for g in gd] + [_fmt_int(data['계약직'])])
        ctk.CTkFrame(f, height=1, fg_color='gray30').grid(row=5, column=0, columnspan=len(gd) + 2, sticky='ew', pady=2)
        _row(f, 6, '평균근속연수', [_fmt_tenure(g['평균근속연수']) for g in gd] + [_fmt_tenure(data['평균근속연수'])])
        _row(f, 7, '1인평균급여(연간)', [_fmt_salary(g['1인평균급여']) for g in gd] + [_fmt_salary(data['1인평균급여'])])

    def _load_capital(self):
        corp = self.selected_corp
        api_key = self.api_key_var.get().strip()
        end_year = str(int(self.end_year_var.get()) - 1)
        self.after(0, lambda: self._render_capital('loading'))

        def run():
            try:
                data = get_capital_changes(api_key, corp['corp_code'], end_year, log_fn=self._log)
                self.after(0, lambda: self._render_capital('done', data=data, year=end_year))
            except Exception as e:
                self._log(f'자본변동 오류: {e}')
                self.after(0, lambda: self._render_capital('error'))

        threading.Thread(target=run, daemon=True).start()

    def _render_capital(self, state, data=None, year=None):
        for w in self._cap_content.winfo_children():
            w.destroy()
        msgs = {
            'initial': ('회사를 선택하면 자본변동 정보가 표시됩니다.', 'gray'),
            'loading': ('불러오는 중...', 'gray'),
            'error': ('데이터를 가져오지 못했습니다.', '#e05252'),
        }
        if state in msgs:
            text, color = msgs[state]
            ctk.CTkLabel(self._cap_content, text=text, text_color=color).grid(row=0, column=0, padx=8, pady=8, sticky='w')
            return
        bold = ctk.CTkFont(weight='bold')
        row_idx = 0
        ctk.CTkLabel(self._cap_content, text=f'■ 증자(감자) 현황  ({year}년도)', font=bold).grid(row=row_idx, column=0, padx=8, pady=(8, 4), sticky='w')
        row_idx += 1
        issu = data.get('증자감자', [])
        if not issu:
            ctk.CTkLabel(self._cap_content, text='  해당사항 없음', text_color='gray60').grid(row=row_idx, column=0, padx=20, pady=4, sticky='w')
            row_idx += 1
        else:
            hdrs = ['발행일', '발행형태', '주식종류', '수량', '액면가(원)', '발행가(원)']
            keys = ['발행일', '발행형태', '주식종류', '수량', '액면가', '발행가']
            widths = [100, 120, 90, 110, 110, 110]
            sub = ctk.CTkFrame(self._cap_content, fg_color='transparent')
            sub.grid(row=row_idx, column=0, padx=12, pady=4, sticky='nw')
            row_idx += 1
            for ci, (h, w) in enumerate(zip(hdrs, widths)):
                ctk.CTkLabel(sub, text=h, font=bold, width=w, anchor='w').grid(row=0, column=ci, padx=4, pady=2)
            ctk.CTkFrame(sub, height=1, fg_color='gray40').grid(row=1, column=0, columnspan=len(hdrs), sticky='ew', pady=1)
            for ri, item in enumerate(issu):
                for ci, (key, w) in enumerate(zip(keys, widths)):
                    ctk.CTkLabel(sub, text=item.get(key, '-'), width=w, anchor='w').grid(row=ri + 2, column=ci, padx=4, pady=3)
        ctk.CTkFrame(self._cap_content, height=1, fg_color='gray30').grid(row=row_idx, column=0, sticky='ew', padx=8, pady=8)
        row_idx += 1
        ctk.CTkLabel(self._cap_content, text=f'■ 자기주식 취득·처분 현황  ({year}년도)', font=bold).grid(row=row_idx, column=0, padx=8, pady=(4, 4), sticky='w')
        row_idx += 1
        treas = data.get('자기주식', [])
        if not treas:
            ctk.CTkLabel(self._cap_content, text='  해당사항 없음', text_color='gray60').grid(row=row_idx, column=0, padx=20, pady=4, sticky='w')
        else:
            hdrs2 = ['주식종류', '기초수량', '취득', '처분', '소각', '기말수량']
            keys2 = ['주식종류', '기초수량', '취득', '처분', '소각', '기말수량']
            widths2 = [90, 130, 100, 100, 100, 130]
            sub2 = ctk.CTkFrame(self._cap_content, fg_color='transparent')
            sub2.grid(row=row_idx, column=0, padx=12, pady=4, sticky='nw')
            for ci, (h, w) in enumerate(zip(hdrs2, widths2)):
                ctk.CTkLabel(sub2, text=h, font=bold, width=w, anchor='w' if ci == 0 else 'e').grid(row=0, column=ci, padx=4, pady=2)
            ctk.CTkFrame(sub2, height=1, fg_color='gray40').grid(row=1, column=0, columnspan=len(hdrs2), sticky='ew', pady=1)
            for ri, item in enumerate(treas):
                for ci, (key, w) in enumerate(zip(keys2, widths2)):
                    anchor = 'w' if ci == 0 else 'e'
                    ctk.CTkLabel(sub2, text=item.get(key, '-'), width=w, anchor=anchor).grid(row=ri + 2, column=ci, padx=4, pady=3)
        self._cap_content.grid_columnconfigure(0, weight=1)

    def _do_download(self):
        if not self.selected_corp:
            self._log('회사를 먼저 선택하세요.')
            return
        report_types = [rt for rt, var in (('사업보고서', self.chk_annual), ('반기보고서', self.chk_semi), ('분기보고서', self.chk_quarter)) if var.get()]
        if not report_types:
            self._log('보고서 유형을 하나 이상 선택하세요.')
            return
        api_key = self.api_key_var.get().strip()
        corp = self.selected_corp
        bgn_de = self.bgn_year_var.get().strip() + '0101'
        end_de = self.end_year_var.get().strip() + '1231'
        base_dir = self.save_dir_var.get()

        def run():
            self.after(0, lambda: self.download_btn.configure(state='disabled', text='다운로드 중...'))
            try:
                self._log(f'[{corp["corp_name"]}] 공시 목록 조회 중...')
                disclosures = list_disclosures(api_key, corp['corp_code'], bgn_de, end_de, report_types=report_types, log_fn=self._log)
                if not disclosures:
                    self._log('해당 조건의 공시가 없습니다.')
                    return
                ok = fail = skip = 0
                for d in disclosures:
                    year = d['report_nm'].split('(')[-1][:4] if '(' in d['report_nm'] else 'unknown'
                    rtype = next((rt for rt in report_types if rt in d['report_nm']), '기타')
                    save_dir = os.path.join(base_dir, corp['corp_name'], f'{rtype}_{year}')
                    result = download_document(api_key, d['rcept_no'], save_dir, log_fn=self._log)
                    if result['status'] == '성공':
                        ok += 1
                    elif result['status'] == '건너뜀':
                        skip += 1
                    else:
                        fail += 1
                self._log(f'완료 — 성공 {ok}건 / 건너뜀 {skip}건 / 실패 {fail}건')
            except Exception as e:
                self._log(f'오류: {e}')
            finally:
                self.after(0, lambda: self.download_btn.configure(state='normal', text='다운로드'))

        threading.Thread(target=run, daemon=True).start()


if __name__ == '__main__':
    app = DartApp()
    app.mainloop()
