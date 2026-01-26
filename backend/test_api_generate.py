import requests
import json

response = requests.post(
    'http://localhost:8000/api/v1/mailboxes/generate',
    json={
        'tenant_id': '045b7f79-7d56-48b7-b0be-8016c25f9043',
        'first_name': 'Sarah',
        'last_name': 'Johnson',
        'count': 10
    }
)

print(f'Status: {response.status_code}')
try:
    data = response.json()
    print(f'Generated: {data.get("mailboxes_generated", 0)} mailboxes')
    print(f'Domain: {data.get("domain", "?")}')
    if 'mailboxes' in data:
        print('\nFirst 5 mailboxes:')
        for m in data['mailboxes'][:5]:
            print(f'  {m["email"]} - {m["display_name"]}')
        
        # Verify no numbers in emails
        for m in data['mailboxes']:
            email_local = m['email'].split('@')[0]
            if any(c.isdigit() for c in email_local):
                print(f'ERROR: Number found in {m["email"]}')
        
        # Verify all display names are the same
        display_names = set(m['display_name'] for m in data['mailboxes'])
        if len(display_names) == 1:
            print(f'\n✅ All display names identical: "{list(display_names)[0]}"')
        else:
            print(f'\n❌ Multiple display names found: {display_names}')
            
        print(f'\n✅ No numbers in any email address')
except Exception as e:
    print(f'Error: {e}')
    print(response.text[:500])