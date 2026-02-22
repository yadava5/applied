# JobTracker - Future Improvements

## Phase 2+ Enhancements

### Email Sync UX Improvements

1. **Prompt for Date Range Before Sync**
   - When user initiates first sync, ask "Since when should we fetch emails?"
   - Provide common options: Last 30 days, Last 3 months, Last 6 months, Last year, Custom date
   - Store user preference for future syncs
   - This prevents fetching years of old emails unnecessarily

2. **Increased Fetch Limits**
   - Default limit increased from 500 to 5000 emails per sync ✅
   - For users with very large mailboxes, consider pagination or background syncing

3. **Multiple Account Support**
   - Allow connecting multiple Gmail accounts
   - Allow connecting multiple iCloud accounts  
   - Each account tracked separately in sync_state

### API Enhancements

1. **Date-based Sync** ✅
   - `POST /sync` now accepts `since_date` parameter
   - `full_sync: true` ignores last sync position

2. **Bulk Delete** ✅
   - `DELETE /emails?source=gmail&confirm=true` - Delete all Gmail emails
   - `DELETE /emails?source=icloud&confirm=true` - Delete all iCloud emails
   - `DELETE /emails?before_date=2026-01-01&confirm=true` - Delete emails before date
   - Preview mode (without confirm) shows count of emails that would be deleted

3. **Account Disconnect with Cleanup** ✅
   - `DELETE /auth/gmail?delete_emails=true` - Disconnect and delete all emails
   - `DELETE /auth/icloud?delete_emails=true` - Disconnect and delete all emails

## Phase 3 - ML Classification

- [ ] Rule-based classification
- [ ] SetFit model training
- [ ] User feedback loop

## Phase 4 - Frontend

- [ ] React/Next.js dashboard
- [ ] Date picker for sync preferences
- [ ] Email visualization
- [ ] Classification review interface
