# allocation.py
# inventory_system_v4.py

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta

class InventoryAllocationSystem:
    """
    A class to manage the end-to-end inventory allocation process.
    VERSION 4: Incorporates dynamic CW identifier and channel-specific expiry rules.
    """

    def __init__(self, forecast_file, stock_file, forecast_mapping, stock_mapping, cw_branch_id=1000):
        self.forecast_file = forecast_file
        self.stock_file = stock_file
        self.forecast_mapping = forecast_mapping
        self.stock_mapping = stock_mapping
        self.cw_branch_id = cw_branch_id  # <-- Dynamic Central Warehouse ID

        # Standardized internal column names
        self.INTERNAL_COLS = {
            'forecast': ['product_id', 'branch_id', 'channel_id', 'forecast_quantity'],
            'stock': ['product_id', 'branch_id', 'stock_available', 'expiry_date']
        }

        # Initialize all dataframes
        self.forecast_df = None
        self.stock_df = None
        self.analysis_df = None
        self.allocation_plan_df = None
        self.unfulfilled_demands_df = pd.DataFrame()
        self.remaining_cw_stock_df = None

    def load_and_clean_data(self):
        """Loads data using mappings and performs cleaning operations."""
        try:
            # Load the raw data
            raw_forecast_df = pd.read_csv(self.forecast_file)
            raw_stock_df = pd.read_csv(self.stock_file)

            # --- DYNAMIC MAPPING ---
            forecast_df = pd.DataFrame()
            for internal_col, user_col in self.forecast_mapping.items():
                if user_col not in raw_forecast_df.columns:
                    return False, f"Column '{user_col}' not found in forecast file."
                forecast_df[internal_col] = raw_forecast_df[user_col]

            stock_df = pd.DataFrame()
            for internal_col, user_col in self.stock_mapping.items():
                if user_col not in raw_stock_df.columns:
                    return False, f"Column '{user_col}' not found in stock file."
                stock_df[internal_col] = raw_stock_df[user_col]

        except Exception as e:
            return False, f"Error reading or mapping files: {e}"

        # --- DATA CLEANING ---
        forecast_df['forecast_quantity'] = pd.to_numeric(forecast_df['forecast_quantity'], errors='coerce').fillna(0).astype(int)
        forecast_df[['product_id', 'branch_id', 'channel_id']] = forecast_df[['product_id', 'branch_id', 'channel_id']].astype(str).astype(int)

        stock_df['expiry_date'] = pd.to_datetime(stock_df['expiry_date'], errors='coerce')
        stock_df['stock_available'] = pd.to_numeric(stock_df['stock_available'], errors='coerce').fillna(0).astype(int)
        stock_df[['product_id', 'branch_id']] = stock_df[['product_id', 'branch_id']].astype(str).astype(int)

        forecast_df.dropna(subset=['product_id', 'branch_id', 'channel_id'], inplace=True)
        stock_df.dropna(subset=['product_id', 'branch_id', 'expiry_date'], inplace=True)

        self.forecast_df = forecast_df
        self.stock_df = stock_df
        return True, "Data loaded, mapped, and cleaned successfully."

    def run_analysis(self):
        """
        Analyzes data at the CHANNEL level to determine needs and statuses.
        """
        # 1. Aggregate destination branch stock (excluding the central warehouse)
        destination_stock = self.stock_df[self.stock_df['branch_id'] != self.cw_branch_id]
        agg_branch_stock = destination_stock.groupby(['product_id', 'branch_id'])['stock_available'].sum().reset_index()
        agg_branch_stock = agg_branch_stock.rename(columns={'stock_available': 'total_stock_available'})

        # 2. Aggregate forecast
        agg_forecast = self.forecast_df.groupby(['product_id', 'branch_id', 'channel_id'])['forecast_quantity'].sum().reset_index()

        # 3. Merge and calculate needs
        analysis_df = pd.merge(agg_forecast, agg_branch_stock, on=['product_id', 'branch_id'], how='left')
        analysis_df['total_stock_available'] = analysis_df['total_stock_available'].fillna(0).astype(int)

        branch_total_forecast = analysis_df.groupby(['product_id', 'branch_id'])['forecast_quantity'].sum().reset_index()
        branch_total_forecast.rename(columns={'forecast_quantity': 'total_forecast_at_branch'}, inplace=True)

        analysis_df = pd.merge(analysis_df, branch_total_forecast, on=['product_id', 'branch_id'])
        analysis_df['branch_net_need'] = analysis_df['total_forecast_at_branch'] - analysis_df['total_stock_available']

        # 4. Determine status
        analysis_df['allocation_status'] = analysis_df['branch_net_need'].apply(
            lambda x: "Allocation Needed" if x > 0 else ("No Allocation Needed" if x == 0 else "Overstock")
        )
        self.analysis_df = analysis_df

    def run_allocation(self, priority_channels=[], priority_branches=[], expiry_rules={}):
        """
        Runs the prioritized FEFO allocation algorithm with channel-specific expiry rules.
        """
        demand_df = self.analysis_df[self.analysis_df['allocation_status'] == 'Allocation Needed'].copy()

        demand_df['priority_rank_channel'] = demand_df['channel_id'].apply(lambda x: 1 if x in priority_channels else 2)
        demand_df['priority_rank_branch'] = demand_df['branch_id'].apply(lambda x: 1 if x in priority_branches else 2)

        prioritized_demand_df = demand_df.sort_values(
            by=['priority_rank_channel', 'priority_rank_branch', 'forecast_quantity'],
            ascending=[True, True, False]
        )

        cw_stock_sorted = self.stock_df[self.stock_df['branch_id'] == self.cw_branch_id].copy().sort_values(by=['product_id', 'expiry_date'])

        branch_need_tracker = demand_df.groupby(['product_id', 'branch_id'])['branch_net_need'].first().to_dict()

        allocation_plan = []
        today = datetime.now()

        for _, demand_row in prioritized_demand_df.iterrows():
            prod_id, branch_id, channel_id = demand_row['product_id'], demand_row['branch_id'], demand_row['channel_id']
            forecast_qty = demand_row['forecast_quantity']

            branch_key = (prod_id, branch_id)
            remaining_branch_need = branch_need_tracker.get(branch_key, 0)

            if remaining_branch_need <= 0:
                continue

            qty_to_fulfill_for_channel = min(forecast_qty, remaining_branch_need)
            fulfilled_for_channel = 0

            # --- Filter stock based on expiry rules for the current channel ---
            min_days_expiry = expiry_rules.get(channel_id, 0) # Default to 0 days if no rule
            required_expiry_date = today + timedelta(days=min_days_expiry)
            
            available_batches = cw_stock_sorted[
                (cw_stock_sorted['product_id'] == prod_id) &
                (cw_stock_sorted['expiry_date'] >= required_expiry_date)
            ]

            if available_batches.empty:
                continue

            for batch_idx, batch_row in available_batches.iterrows():
                if batch_row['stock_available'] == 0: continue

                take = min(qty_to_fulfill_for_channel - fulfilled_for_channel, batch_row['stock_available'])

                allocation_plan.append({
                    'product_id': prod_id, 'from_branch': self.cw_branch_id, 'to_branch': branch_id,
                    'channel_id': channel_id, 'quantity_allocated': take, 'expiry_date': batch_row['expiry_date']
                })

                cw_stock_sorted.loc[batch_idx, 'stock_available'] -= take
                fulfilled_for_channel += take

                if fulfilled_for_channel == qty_to_fulfill_for_channel: break

            branch_need_tracker[branch_key] -= fulfilled_for_channel

        unfulfilled_demands = []
        for (prod_id, branch_id), remaining_need in branch_need_tracker.items():
            if remaining_need > 0:
                total_initial_need = self.analysis_df[(self.analysis_df['product_id']==prod_id) & (self.analysis_df['branch_id']==branch_id)]['branch_net_need'].iloc[0]
                unfulfilled_demands.append({
                    'product_id': prod_id, 'branch_id': branch_id, 'needed': total_initial_need,
                    'fulfilled': total_initial_need - remaining_need, 'unfulfilled': remaining_need
                })

        self.allocation_plan_df = pd.DataFrame(allocation_plan)
        self.unfulfilled_demands_df = pd.DataFrame(unfulfilled_demands)
        self.remaining_cw_stock_df = cw_stock_sorted[cw_stock_sorted['stock_available'] > 0]


    # --- VISUALIZATION METHODS (No changes needed) ---
    def get_analysis_charts(self):
        sns.set_style("whitegrid")
        status_counts = self.analysis_df.drop_duplicates(subset=['product_id', 'branch_id'])['allocation_status'].value_counts()
        fig1, ax1 = plt.subplots(figsize=(6,6))
        ax1.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', startangle=140, colors=['#ff9999','#66b3ff','#99ff99'])
        ax1.set_title('Overall Inventory Status (by Branch)', fontsize=16)
        channel_demand = self.analysis_df[self.analysis_df['allocation_status'] == 'Allocation Needed'].groupby('channel_id')['forecast_quantity'].sum().nlargest(10)
        fig2, ax2 = plt.subplots(figsize=(10,6))
        sns.barplot(x=channel_demand.index, y=channel_demand.values, hue=channel_demand.index, palette='magma', order=channel_demand.index, ax=ax2, legend=False)
        ax2.set_title('Top 10 Channels by Forecast Demand', fontsize=16)
        return fig1, fig2

    def get_allocation_charts(self):
        sns.set_style("whitegrid")
        total_allocated = self.allocation_plan_df['quantity_allocated'].sum() if not self.allocation_plan_df.empty else 0
        total_unfulfilled = self.unfulfilled_demands_df['unfulfilled'].sum() if not self.unfulfilled_demands_df.empty else 0
        fig1 = None
        if total_allocated > 0 or total_unfulfilled > 0:
            fig1, ax1 = plt.subplots(figsize=(6,6))
            ax1.pie([total_allocated, total_unfulfilled], labels=['Fulfilled', 'Unfulfilled'], autopct='%1.1f%%', colors=['#4CAF50', '#F44336'])
            ax1.set_title('Overall Demand Fulfillment Status', fontsize=16)
        alloc_by_channel = self.allocation_plan_df.groupby('channel_id')['quantity_allocated'].sum().nlargest(10) if not self.allocation_plan_df.empty else pd.Series()
        fig2, ax2 = plt.subplots(figsize=(12, 7))
        if not alloc_by_channel.empty:
            sns.barplot(x=alloc_by_channel.index, y=alloc_by_channel.values, hue=alloc_by_channel.index, palette='crest', order=alloc_by_channel.index, ax=ax2, legend=False)
        ax2.set_title('Top 10 Channels by Quantity Allocated', fontsize=16)
        return fig1, fig2