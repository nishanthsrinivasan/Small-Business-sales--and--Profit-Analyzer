import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression
from prophet import Prophet

def analytics_forecasting_page():
    st.title("📈 AI Forecast")

    if "sales_data" not in st.session_state:
        st.warning("Please load Transaction or CSV data in Analytics first!");return

    df=st.session_state.sales_data.copy();df['date']=pd.to_datetime(df['date'])

    if "data_source" in st.session_state:source_type=st.session_state.data_source
    else:source_type="Transactions" if "transaction_id" in df.columns else "CSV File"

    st.subheader("📅 Forecast Configuration")
    min_date=df['date'].min().date();max_date=df['date'].max().date()
    selected_range=st.slider("Select Historical Data Range",min_value=min_date,max_value=max_date,value=(min_date,max_date),format="YYYY-MM-DD")
    days=st.slider("Select Forecast Days",7,90,30)

    start_date,end_date=selected_range
    df_filtered=df[(df['date'].dt.date>=start_date)&(df['date'].dt.date<=end_date)]
    if len(df_filtered)<2:st.error("Insufficient data in the selected range. Please expand the historical slider.");return

    df_daily=df_filtered.groupby("date")["profit"].sum().reset_index().rename(columns={"date":"sale_date","profit":"amount"})
    st.divider()

    st.subheader("🔵 Linear Regression Forecast")
    df_daily["t"]=np.arange(len(df_daily));poly=PolynomialFeatures(2)
    model=LinearRegression().fit(poly.fit_transform(df_daily[["t"]]),df_daily["amount"])
    future_t=np.arange(len(df_daily),len(df_daily)+days)
    forecast_lr=model.predict(poly.transform(future_t.reshape(-1,1)))
    future_dates=pd.date_range(df_daily.sale_date.iloc[-1],periods=days+1)[1:]

    fig1=px.line(title="Linear Regression Prediction")
    fig1.add_scatter(x=df_daily.sale_date,y=df_daily.amount,name="History")
    fig1.add_scatter(x=future_dates,y=forecast_lr,name="Forecast")
    st.plotly_chart(fig1);fig1.write_image("linear_forecast.png")

    st.subheader("🟢 Prophet Forecast")
    p_df=df_daily.rename(columns={"sale_date":"ds","amount":"y"})
    model_p=Prophet().fit(p_df);future_p=model_p.make_future_dataframe(periods=days)
    forecast_p=model_p.predict(future_p)

    fig2=px.line(title="Prophet Algorithm Prediction")
    fig2.add_scatter(x=p_df["ds"],y=p_df["y"],name="History")
    fig2.add_scatter(x=forecast_p[forecast_p["ds"]>p_df["ds"].max()]["ds"],y=forecast_p["yhat"],name="Forecast")
    st.plotly_chart(fig2);fig2.write_image("forecast_chart.png")

    st.divider();st.subheader("📈 Business Prediction")
    total_f=forecast_p.tail(days)["yhat"].sum();status='PROFIT' if total_f>0 else 'LOSS'

    k1,k2,k3=st.columns(3)
    k1.metric("Data Source",source_type);k2.metric("Historical Days",len(df_daily));k3.metric("Forecast days",f"{days} Days")

    res_text=f"The business is predicted to be in {status} by INR {abs(total_f):,.2f} over the next {days} days."
    st.session_state["forecast_result"]=res_text
    (st.success if status=='PROFIT' else st.error)(res_text)