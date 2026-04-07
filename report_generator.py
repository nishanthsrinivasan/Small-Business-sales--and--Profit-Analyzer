import streamlit as st
import pandas as pd
from fpdf import FPDF
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import os
import base64
from datetime import datetime
from db_connection import get_connection

def clean_text(text):
    if text is None: return ""
    text = str(text)
    replacements = {"\u20b9":"INR","\u2014":"-","\u2013":"-","\u2264":"<=","\u2265":">=","\u00d7":"x","\u2019":"'","\u2018":"'","\u201c":'"',"\u201d":'"',"\u2026":"...","\u00b0":" deg","\u00b1":"+/-"}
    for orig,repl in replacements.items(): text = text.replace(orig,repl)
    return text.encode('latin-1','replace').decode('latin-1')

class PDFReport(FPDF):
    def header(self):
        if self.page_no() == 1:
            name = st.session_state.get("selected_business_name", st.session_state.get("business_name","BUSINESS REPORT"))
            self.set_font('Arial','B',22); self.set_text_color(30,30,30)
            self.cell(0,15,clean_text(name.upper()),0,1,'C')
            self.set_draw_color(52,152,219); self.set_line_width(0.8)
            self.line(10,self.get_y(),200,self.get_y()); self.ln(3)
        self.set_font('Arial','I',8); self.set_text_color(120,120,120)
        self.cell(0,5,clean_text(f"Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}"),0,1,'R')
        self.set_text_color(0,0,0); self.ln(3)

    def footer(self):
        self.set_y(-15); self.set_font('Arial','I',8); self.set_text_color(120,120,120)
        self.cell(0,10,clean_text(f'Page {self.page_no()}'),0,0,'C'); self.set_text_color(0,0,0)

    def section_title(self,title):
        self.ln(4); self.set_font("Arial","B",16); self.set_text_color(30,30,30)
        self.cell(0,10,clean_text(title),0,1); self.set_draw_color(52,152,219); self.set_line_width(0.5)
        self.line(10,self.get_y(),200,self.get_y()); self.ln(4); self.set_text_color(0,0,0)

    def sub_heading(self,title):
        self.set_font("Arial","B",12); self.set_text_color(44,62,80)
        self.cell(0,8,clean_text(title),0,1); self.set_text_color(0,0,0)

    def stat_row(self,label,value,r=0,g=0,b=0):
        self.set_font("Arial","",11); self.set_text_color(80,80,80)
        self.cell(120,8,clean_text(label),0,0); self.set_font("Arial","B",11)
        self.set_text_color(r,g,b); self.cell(0,8,clean_text(str(value)),0,1); self.set_text_color(0,0,0)

def save_fig(fig,name,width=820,height=420):
    fig.update_layout(paper_bgcolor='white',plot_bgcolor='white',font=dict(family="Arial",size=12,color="#2c3e50"),margin=dict(l=40,r=40,t=50,b=40))
    pio.write_image(fig,name,width=width,height=height,scale=2); return name

def get_report_data():
    biz_id = st.session_state.get("business_id") or st.session_state.get("selected_business_id")
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT setting_value FROM system_settings WHERE setting_name='low_stock_threshold' AND business_id=?",(biz_id,))
    res_t = cursor.fetchone()
    try: threshold = int(dict(res_t)["setting_value"]) if res_t else 5
    except: threshold = 5
    cursor.execute("SELECT * FROM inventory WHERE business_id=?",(biz_id,))
    rows = [dict(r) for r in cursor.fetchall() or []]
    inv_df = pd.DataFrame(rows); conn.close()
    return inv_df, threshold

def add_table(pdf,df,title,header_color=(52,152,219)):
    pdf.ln(3); pdf.sub_heading(title)
    if df.empty:
        pdf.set_font("Arial","I",9); pdf.set_text_color(150,150,150)
        pdf.cell(0,6,"No items found in this category.",0,1); pdf.set_text_color(0,0,0); return
    pdf.set_font("Arial","",8); col_width=(pdf.w-20)/len(df.columns)
    pdf.set_fill_color(*header_color); pdf.set_text_color(255,255,255); pdf.set_font("Arial","B",8)
    for col in df.columns: pdf.cell(col_width,8,clean_text(str(col).replace("_"," ").title()[:20]),1,0,'C',True)
    pdf.ln(); pdf.set_text_color(30,30,30); pdf.set_font("Arial","",8)
    for i,(_,row) in enumerate(df.iterrows()):
        pdf.set_fill_color(245,248,252) if i%2==0 else pdf.set_fill_color(255,255,255)
        for val in row: pdf.cell(col_width,7,clean_text(str(val))[:22],1,0,'L',True)
        pdf.ln()
    pdf.set_text_color(0,0,0); pdf.ln(2)

def generate_full_report():
    biz_id = st.session_state.get("business_id") or st.session_state.get("selected_business_id")
    if not biz_id: st.error("Business not selected."); return None
    if "data" not in st.session_state: st.error("Transaction data not found. Please load transactions first."); return None

    inv_df,threshold = get_report_data()
    txn_df = st.session_state.data.copy()

    qty_col  = next((c for c in inv_df.columns if c.lower() in ['stock','quantity','qty']),'stock')
    name_col = next((c for c in inv_df.columns if 'name' in c.lower() or 'product' in c.lower()),'product_name')
    cost_col = next((c for c in inv_df.columns if 'cost' in c.lower()),None)
    cat_col  = next((c for c in inv_df.columns if 'cat' in c.lower()),None)

    inv_df[qty_col] = pd.to_numeric(inv_df[qty_col],errors='coerce').fillna(0)
    if cost_col: inv_df[cost_col] = pd.to_numeric(inv_df[cost_col],errors='coerce').fillna(0)

    out_stock_df = inv_df[inv_df[qty_col]<=0].copy()
    low_stock_df = inv_df[(inv_df[qty_col]>0)&(inv_df[qty_col]<=threshold)].copy()
    healthy_df   = inv_df[inv_df[qty_col]>threshold].copy()

    total_products = len(inv_df)
    total_val  = (inv_df[qty_col]*inv_df[cost_col]).sum() if cost_col else 0
    out_count  = len(out_stock_df); low_count = len(low_stock_df); healthy_count = len(healthy_df)

    show_cols = [name_col,qty_col]
    if cat_col: show_cols.append(cat_col)
    if cost_col: show_cols.append(cost_col)

    total_transactions = len(txn_df)
    revenue = pd.to_numeric(txn_df.get("revenue",  pd.Series([0])),errors='coerce').sum()
    expense = pd.to_numeric(txn_df.get("expenses", pd.Series([0])),errors='coerce').sum()
    profit  = pd.to_numeric(txn_df.get("profit",   pd.Series([0])),errors='coerce').sum()

    pdf = PDFReport(); pdf.set_auto_page_break(True,18)

    # PAGE 1 — INVENTORY
    pdf.add_page(); pdf.section_title("Inventory Analysis")
    pdf.stat_row("Total Products:",                          f"{total_products}",         30,30,30)
    pdf.stat_row("Total Inventory Value (Cost Price):",      f"INR {total_val:,.2f}",     41,128,185)
    pdf.stat_row("Low Stock Alert Threshold:",               f"{threshold} units",         243,156,18)
    pdf.stat_row("Healthy Stock Products:",                  f"{healthy_count}",           39,174,96)
    pdf.stat_row("Out of Stock Products (stock = 0):",       f"{out_count}",              200,0,0)
    pdf.stat_row(f"Low Stock Products (1 to {threshold}):",  f"{low_count}",              243,156,18)
    pdf.ln(3)

    fig_pie = go.Figure(data=[go.Pie(
        labels=["Out of Stock",f"Low Stock (<= {threshold})","Healthy Stock"],
        values=[out_count,low_count,healthy_count], hole=0.35,
        marker=dict(colors=["#E74C3C","#F39C12","#27AE60"],line=dict(color='white',width=2)),
        textinfo='label+percent+value', textfont=dict(size=12)
    )])
    fig_pie.update_layout(title=dict(text="Stock Level Status",font=dict(size=16,color="#2c3e50")),
        legend=dict(orientation="h",yanchor="bottom",y=-0.25,xanchor="center",x=0.5),paper_bgcolor='white')
    pdf.image(save_fig(fig_pie,"inv_pie.png",width=700,height=420),w=155,x=28); pdf.ln(4)

    if cat_col and not inv_df.empty:
        cat_summary = inv_df.groupby(cat_col)[qty_col].sum().reset_index(); cat_summary.columns=['Category','Total Stock']
        cat_summary = cat_summary.sort_values('Total Stock',ascending=False)
        fig_bar = px.bar(cat_summary,x='Category',y='Total Stock',title="Stock Distribution by Category",
            color='Category',color_discrete_sequence=px.colors.qualitative.Set2,text='Total Stock')
        fig_bar.update_traces(textposition='outside')
        fig_bar.update_layout(xaxis_title="Category",yaxis_title="Total Stock Units",showlegend=False,paper_bgcolor='white',plot_bgcolor='#f8f9fa')
        pdf.sub_heading("Stock Distribution by Category"); pdf.image(save_fig(fig_bar,"cat_bar.png",width=820,height=400),w=175,x=10); pdf.ln(4)

    add_table(pdf,out_stock_df[show_cols].copy() if not out_stock_df.empty else pd.DataFrame(columns=show_cols),f"Out of Stock - {out_count} item(s)",header_color=(231,76,60))
    add_table(pdf,low_stock_df[show_cols].copy() if not low_stock_df.empty else pd.DataFrame(columns=show_cols),f"Low Stock (threshold <= {threshold}) - {low_count} item(s)",header_color=(243,156,18))

    # PAGE 2 — TRANSACTIONS
    pdf.add_page(); pdf.section_title("Transaction Summary")
    pdf.stat_row("Total Transactions:", f"{total_transactions}", 30,30,30)
    pdf.stat_row("Total Revenue:",      f"INR {revenue:,.2f}",  41,128,185)
    pdf.stat_row("Total Expenses:",     f"INR {expense:,.2f}",  231,76,60)
    profit_color = (39,174,96) if profit>=0 else (231,76,60)
    pdf.set_font("Arial","B",13); pdf.set_text_color(80,80,80)
    pdf.cell(120,9,"Net Profit:",0,0); pdf.set_text_color(*profit_color)
    pdf.cell(0,9,clean_text(f"INR {profit:,.2f}"),0,1); pdf.set_text_color(0,0,0); pdf.ln(4)

    fig_rev_exp = go.Figure(data=[
        go.Bar(name='Revenue', x=['Financials'],y=[revenue],marker_color='#3498DB',text=[f"INR {revenue:,.0f}"],textposition='outside'),
        go.Bar(name='Expenses',x=['Financials'],y=[expense],marker_color='#E74C3C',text=[f"INR {expense:,.0f}"],textposition='outside'),
        go.Bar(name='Profit',  x=['Financials'],y=[profit], marker_color='#27AE60',text=[f"INR {profit:,.0f}"], textposition='outside'),
    ])
    fig_rev_exp.update_layout(title="Revenue vs Expenses vs Profit",barmode='group',yaxis_title="Amount (INR)",
        paper_bgcolor='white',plot_bgcolor='#f8f9fa',legend=dict(orientation="h",yanchor="bottom",y=-0.25,xanchor="center",x=0.5))
    pdf.image(save_fig(fig_rev_exp,"rev_exp.png",width=820,height=420),w=175,x=10); pdf.ln(4)

    if "date" in txn_df.columns:
        txn_df["date"] = pd.to_datetime(txn_df["date"],errors='coerce'); txn_df = txn_df.dropna(subset=["date"])
        trend = txn_df.groupby("date")["profit"].sum().reset_index()
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=trend["date"],y=trend["profit"],mode='lines',name='Daily Profit',
            line=dict(color='#27AE60',width=1.5),fill='tozeroy',fillcolor='rgba(39,174,96,0.15)'))
        trend["rolling_avg"] = trend["profit"].rolling(window=30,min_periods=1).mean()
        fig_trend.add_trace(go.Scatter(x=trend["date"],y=trend["rolling_avg"],mode='lines',name='30-Day Avg',
            line=dict(color='#E74C3C',width=2,dash='dash')))
        fig_trend.update_layout(title="Profit Trend Over Time",xaxis_title="Date",yaxis_title="Profit (INR)",
            paper_bgcolor='white',plot_bgcolor='#f8f9fa',legend=dict(orientation="h",yanchor="bottom",y=-0.25,xanchor="center",x=0.5))
        pdf.sub_heading("Profit Trend Over Time"); pdf.image(save_fig(fig_trend,"trend.png",width=820,height=420),w=175,x=10); pdf.ln(4)

        txn_df["month"] = txn_df["date"].dt.to_period("M").astype(str)
        monthly = txn_df.groupby("month")[["revenue","expenses","profit"]].sum().reset_index().tail(12)
        fig_monthly = go.Figure()
        fig_monthly.add_trace(go.Bar(x=monthly["month"],y=monthly["revenue"],name="Revenue", marker_color="#3498DB"))
        fig_monthly.add_trace(go.Bar(x=monthly["month"],y=monthly["expenses"],name="Expenses",marker_color="#E74C3C"))
        fig_monthly.add_trace(go.Bar(x=monthly["month"],y=monthly["profit"],  name="Profit",  marker_color="#27AE60"))
        fig_monthly.update_layout(title="Monthly Financial Overview (Last 12 Months)",barmode='group',
            xaxis_title="Month",yaxis_title="Amount (INR)",paper_bgcolor='white',plot_bgcolor='#f8f9fa',
            legend=dict(orientation="h",yanchor="bottom",y=-0.3,xanchor="center",x=0.5),xaxis=dict(tickangle=-45))
        pdf.sub_heading("Monthly Financial Overview"); pdf.image(save_fig(fig_monthly,"monthly.png",width=820,height=440),w=175,x=10)

    # PAGE 3 — FORECAST
    pdf.add_page(); pdf.section_title("AI Forecast Analysis")
    forecast_text = st.session_state.get("forecast_result",None)
    if forecast_text:
        pdf.sub_heading("Forecasted Business Prediction Summary"); pdf.set_font("Arial","",10); pdf.set_text_color(30,30,30)
        for line in clean_text(str(forecast_text)).split('\n'):
            if line.strip(): pdf.multi_cell(0,7,line.strip())
        pdf.ln(4)
    else:
        pdf.set_font("Arial","I",10); pdf.set_text_color(150,150,150)
        pdf.cell(0,8,"(No forecast prediction text - run the Forecast page first)",0,1); pdf.set_text_color(0,0,0); pdf.ln(4)

    for path,label in [("prophet_forecast.png","Prophet Time-Series Forecast Chart"),("linear_forecast.png","Linear Regression Forecast Chart")]:
        if os.path.exists(path): pdf.sub_heading(label); pdf.image(path,w=175,x=10); pdf.ln(5)
        else:
            pdf.set_font("Arial","I",10); pdf.set_text_color(150,150,150)
            pdf.cell(0,8,f"({label} not found - run the Forecast page first)",0,1); pdf.set_text_color(0,0,0); pdf.ln(4)

    filename = f"Full_Business_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(filename)
    for tmp in ["inv_pie.png","cat_bar.png","rev_exp.png","trend.png","monthly.png"]:
        if os.path.exists(tmp): os.remove(tmp)
    return filename

def render_report():
    st.header("📊 Business Performance Report"); st.markdown("---")
    biz_id = st.session_state.get("business_id") or st.session_state.get("selected_business_id")
    if not biz_id: st.warning("Please select a business first."); return
    if "data" not in st.session_state: st.warning("Transaction data not loaded. Please visit the Transactions page first."); return
    st.info("The report will include:\n- Inventory Analysis\n- Transaction Summary\n- AI Forecast Analysis")
    if st.button("Generate Final PDF Report", type="primary"):
        with st.spinner("Generating PDF report... Please wait."):
            file = generate_full_report()
        if file:
            st.success("Report Generated Successfully!")
            col1,col2 = st.columns([1,3])
            with col1:
                with open(file,"rb") as f:
                    st.download_button("Download PDF Report",f,file_name=file,mime="application/pdf",type="primary")
            st.markdown("### Preview")
            with open(file,"rb") as f: base64_pdf = base64.b64encode(f.read()).decode("utf-8")
            st.markdown(f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="900" type="application/pdf"></iframe>',unsafe_allow_html=True)

if __name__ == "__main__":
    render_report()