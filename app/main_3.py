# app.py 
# app_v3.py

import streamlit as st
import pandas as pd
from utils.allocation_3 import InventoryAllocationSystem # <-- IMPORT THE NEW CLASS

# --- Page Configuration ---
st.set_page_config(layout="wide", page_title="Generalized Inventory Allocation")

# --- App Title ---
st.title("📦 Generalized Inventory Allocation Tool (v3)")
st.markdown("A flexible tool to map, analyze, and allocate inventory based on your specific data structure.")

# --- Session State Initialization ---
if 'system' not in st.session_state:
    st.session_state.system = None
    st.session_state.analysis_run = False
    st.session_state.allocation_run = False
    st.session_state.forecast_cols = []
    st.session_state.stock_cols = []
    st.session_state.files_uploaded = False

# --- Main Application Tabs ---
tab1, tab2, tab3 = st.tabs(["1. Upload & Map Data", "2. Analysis Results", "3. Allocation Plan"])

# =================================================================================================
# TAB 1: UPLOAD AND MAP DATA
# =================================================================================================
with tab1:
    st.header("Upload and Map Your Data")
    
    col1, col2 = st.columns(2)
    with col1:
        forecast_file = st.file_uploader("Upload Forecast CSV", type="csv")
    with col2:
        stock_file = st.file_uploader("Upload Stock CSV", type="csv")

    # --- Read columns once files are uploaded ---
    if forecast_file and stock_file and not st.session_state.files_uploaded:
        try:
            st.session_state.forecast_cols = pd.read_csv(forecast_file, nrows=0).columns.tolist()
            st.session_state.stock_cols = pd.read_csv(stock_file, nrows=0).columns.tolist()
            st.session_state.files_uploaded = True
        except Exception as e:
            st.error(f"Could not read file headers. Error: {e}")

    # --- Display mapping interface if columns are loaded ---
    if st.session_state.files_uploaded:
        st.markdown("---")
        st.subheader("Map your columns to the required fields:")
        
        # --- Mapping Forms ---
        map_col1, map_col2 = st.columns(2)
        
        with map_col1:
            st.info("Forecast Data Mapping")
            forecast_map = {
                'product_id': st.selectbox("Product ID", st.session_state.forecast_cols, key='f_pid'),
                'branch_id': st.selectbox("Branch/Plant ID", st.session_state.forecast_cols, key='f_bid'),
                'channel_id': st.selectbox("Channel ID", st.session_state.forecast_cols, key='f_cid'),
                'forecast_quantity': st.selectbox("Forecast Quantity", st.session_state.forecast_cols, key='f_qty')
            }
        
        with map_col2:
            st.info("Stock Data Mapping")
            stock_map = {
                'product_id': st.selectbox("Product ID", st.session_state.stock_cols, key='s_pid'),
                'branch_id': st.selectbox("Branch/Plant ID", st.session_state.stock_cols, key='s_bid'),
                'stock_available': st.selectbox("Available Stock Quantity", st.session_state.stock_cols, key='s_qty'),
                'expiry_date': st.selectbox("Expiry Date", st.session_state.stock_cols, key='s_exp')
            }
        
        st.markdown("---")
        if st.button("1. Analyze Inventory Needs", type="primary"):
            with st.spinner('Loading, mapping, and analyzing...'):
                system = InventoryAllocationSystem(forecast_file, stock_file, forecast_map, stock_map)
                success, message = system.load_and_clean_data()
                if success:
                    system.run_analysis()
                    st.session_state.system = system
                    st.session_state.analysis_run = True
                    st.session_state.allocation_run = False # Reset allocation
                    st.success(message)
                    st.info("Analysis complete! Proceed to the 'Analysis Results' tab.")
                else:
                    st.error(message)

# =================================================================================================
# TAB 2: ANALYSIS RESULTS
# =================================================================================================
with tab2:
    st.header("📊 Inventory Analysis Results")
    if not st.session_state.analysis_run:
        st.warning("Please upload, map, and run the analysis on the first tab.")
    else:
        system = st.session_state.system
        
        # --- Analysis Charts ---
        fig_pie, fig_bar = system.get_analysis_charts()
        col1, col2 = st.columns([1, 2])
        with col1:
            st.pyplot(fig_pie)
        with col2:
            st.pyplot(fig_bar)
        
        st.markdown("---")
        
        # --- Detailed Data with Styling ---
        st.subheader("Full Channel-Level Analysis Data")
        def style_status_column(val):
            color = {'Overstock': '#ffcdd2', 'Allocation Needed': '#ffecb3', 'No Allocation Needed': '#c8e6c9'}.get(val, 'white')
            return f'background-color: {color}; color: black;'
        styled_df = system.analysis_df.style.applymap(style_status_column, subset=['allocation_status'])
        st.dataframe(styled_df, height=500, use_container_width=True)

# =================================================================================================
# TAB 3: ALLOCATION PLAN
# =================================================================================================
with tab3:
    st.header("🚚 Allocation Plan & Results")
    if not st.session_state.analysis_run:
        st.warning("Please run the analysis on the first tab before generating an allocation plan.")
    else:
        system = st.session_state.system
        
        # --- Allocation Controls ---
        with st.expander("⚙️ Set Allocation Priorities", expanded=True):
            needy_channels = sorted(system.analysis_df[system.analysis_df['allocation_status'] == 'Allocation Needed']['channel_id'].unique())
            needy_branches = sorted(system.analysis_df[system.analysis_df['allocation_status'] == 'Allocation Needed']['branch_id'].unique())
            
            priority_channels = st.multiselect(
                "Select Priority Channels (Highest Priority)",
                options=needy_channels,
                help="Stock will be allocated to these channels first, across all branches."
            )
            
            priority_branches = st.multiselect(
                "Select Priority Branches (Second Priority)",
                options=needy_branches,
                help="After priority channels are served, stock will go to these branches."
            )

            if st.button("2. Generate Allocation Plan", type="primary"):
                with st.spinner('Generating strategic plan...'):
                    system.run_allocation(priority_channels=priority_channels, priority_branches=priority_branches)
                    st.session_state.system = system
                    st.session_state.allocation_run = True
                    st.success("Strategic allocation plan generated!")

        st.markdown("---")

        # --- Display Allocation Results ---
        if st.session_state.allocation_run:
            fig_fulfillment, fig_channel_alloc = system.get_allocation_charts()
            
            col1, col2 = st.columns([1, 2])
            with col1:
                if fig_fulfillment:
                    st.pyplot(fig_fulfillment)
            with col2:
                st.pyplot(fig_channel_alloc)
            
            sub_tab1, sub_tab2, sub_tab3 = st.tabs(["✅ Allocation Plan", "⚠️ Unfulfilled Demands", "📦 Remaining Warehouse Stock"])
            
            with sub_tab1:
                df_plan = system.allocation_plan_df
                st.dataframe(df_plan)
                if not df_plan.empty:
                    st.download_button("Download Plan as CSV", df_plan.to_csv(index=False).encode('utf-8'), "allocation_plan.csv", "text/csv")

            with sub_tab2:
                df_unfulfilled = system.unfulfilled_demands_df
                if not df_unfulfilled.empty:
                    st.dataframe(df_unfulfilled)
                    st.download_button("Download Unfulfilled as CSV", df_unfulfilled.to_csv(index=False).encode('utf-8'), "unfulfilled_demands.csv", "text/csv")
                else:
                    st.success("No unfulfilled demands!")

            with sub_tab3:
                df_remaining = system.remaining_cw_stock_df
                st.dataframe(df_remaining)
                if not df_remaining.empty:
                    st.download_button("Download Remaining Stock as CSV", df_remaining.to_csv(index=False).encode('utf-8'), "remaining_warehouse_stock.csv", "text/csv")