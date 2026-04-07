import streamlit as st
import pandas as pd
from fpdf import FPDF
import matplotlib.pyplot as plt
import os
import base64
from datetime import datetime
from db_connection import get_connection

# ---------------- CLEAN TEXT ----------------
def clean_text(text):
    if text is None:
        return ""
    return str(text)

# ---------------- PDF CLASS ----------------
class PDFReport(FPDF):
    def header(self):
        if self.page_no() == 1:
            name = st.session_state.get("selected_business_name", "BUSINESS REPORT")
            self.set_font('Arial','B',18)
            self.cell(0,10,name,0,1,'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial','I',8)
        self.cell(0,10,f'Page {self.page_no()}',0,0,'C')

    def section_title(self,title):
        self.set_font("Arial","B",14)
        self.cell(0,10,title,0,1)

    def stat_row(self,label,value):
        self.set_font("Arial","",10)
        self.cell(100,8,label,0,0)
        self.cell(0,8,str(value),0,1)

# ---------------- TABLE FUNCTION ----------------
def add_table(pdf, df, title):
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, title, 0, 1)

    if df.empty:
        pdf.set_font("Arial", "I", 10)
        pdf.cell(0, 6, "No data available", 0, 1)
        return

    pdf.set_font("Arial", "B", 8)
    col_width = (pdf.w - 20) / len(df.columns)

    # Header
    for col in df.columns:
        pdf.cell(col_width, 8, str(col)[:15], 1, 0, 'C')
    pdf.ln()

    # Rows
    pdf.set_font("Arial", "", 8)
    for _, row in df.iterrows():
        for val in row:
            pdf.cell(col_width, 7, str(val)[:15], 1, 0)
        pdf.ln()

# ---------------- MATPLOTLIB CHARTS ----------------
def create_pie_chart(out_count, low_count, healthy_count):
    labels = ['Out of Stock', 'Low Stock', 'Healthy']
    values = [out_count, low_count, healthy_count]

    plt.figure()
    plt.pie(values, labels=labels, autopct='%1.1f%%')
    plt.title("Stock Status")

    filename = "pie.png"
    plt.savefig(filename)
    plt.close()
    return filename

def create_bar_chart(revenue, expense, profit):
    labels = ['Revenue', 'Expenses', 'Profit']
    values = [revenue, expense, profit]

    plt.figure()
    plt.bar(labels, values)
    plt.title("Financial Summary")

    filename = "bar.png"
    plt.savefig(filename)
    plt.close()
    return filename

# ---------------- DATA FETCH ----------------
def get_report_data():
    biz_id = st.session_state.get("business_id")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM inventory WHERE business_id=?", (biz_id,))
    rows = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return pd.DataFrame(rows)

# ---------------- MAIN REPORT ----------------
def generate_full_report():
    biz_id = st.session_state.get("business_id")

    if not biz_id:
        st.error("Select business")
        return None

    inv_df = get_report_data()
    txn_df = st.session_state.get("data", pd.DataFrame())

    inv_df["stock"] = pd.to_numeric(inv_df.get("stock", 0), errors='coerce').fillna(0)

    out_df = inv_df[inv_df["stock"] <= 0]
    low_df = inv_df[(inv_df["stock"] > 0) & (inv_df["stock"] <= 5)]
    healthy_df = inv_df[inv_df["stock"] > 5]

    revenue = txn_df.get("revenue", pd.Series([0])).sum()
    expense = txn_df.get("expenses", pd.Series([0])).sum()
    profit = txn_df.get("profit", pd.Series([0])).sum()

    pdf = PDFReport()

    # -------- PAGE 1 --------
    pdf.add_page()
    pdf.section_title("Inventory Analysis")

    pdf.stat_row("Total Products", len(inv_df))
    pdf.stat_row("Out of Stock", len(out_df))
    pdf.stat_row("Low Stock", len(low_df))
    pdf.stat_row("Healthy", len(healthy_df))

    # Chart
    pie_img = create_pie_chart(len(out_df), len(low_df), len(healthy_df))
    pdf.image(pie_img, w=150)

    # Tables
    show_cols = ["product_name", "stock"]

    add_table(pdf, out_df[show_cols], "Out of Stock Items")
    add_table(pdf, low_df[show_cols], "Low Stock Items")

    # -------- PAGE 2 --------
    pdf.add_page()
    pdf.section_title("Transaction Summary")

    pdf.stat_row("Revenue", revenue)
    pdf.stat_row("Expenses", expense)
    pdf.stat_row("Profit", profit)

    bar_img = create_bar_chart(revenue, expense, profit)
    pdf.image(bar_img, w=150)

    # -------- PAGE 3 --------
    pdf.add_page()
    pdf.section_title("Forecast")

    forecast = st.session_state.get("forecast_result", "No forecast available")
    pdf.multi_cell(0, 8, forecast)

    # Save PDF
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(filename)

    # Cleanup
    for f in [pie_img, bar_img]:
        if os.path.exists(f):
            os.remove(f)

    return filename

# ---------------- UI ----------------
def render_report():
    st.header("📊 Business Report")

    if st.button("Generate Report"):
        file = generate_full_report()

        if file:
            st.success("Report Generated")

            with open(file, "rb") as f:
                st.download_button("Download PDF", f, file_name=file)

            with open(file, "rb") as f:
                base64_pdf = base64.b64encode(f.read()).decode("utf-8")

            st.markdown(
                f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800"></iframe>',
                unsafe_allow_html=True
            )

if __name__ == "__main__":
    render_report()