from app.services.email_generator import email_generator

results = email_generator.generate("Jack", "Zuvelek", "example.com", 50)
print(f"Generated {len(results)} emails\n")

# CRITICAL: Verify NO numbers in any email
for r in results:
    local = r['email'].split('@')[0]
    assert not any(c.isdigit() for c in local), f"NUMBER FOUND IN: {r['email']}"

# Verify all display names are the same
assert all(r['display_name'] == "Jack Zuvelek" for r in results), "Display names should all be identical"

# Verify all unique
emails = [r['email'] for r in results]
assert len(emails) == len(set(emails)), "Duplicates found!"

# Print sample
for r in results[:15]:
    print(f"{r['display_name']},{r['email']},{r['password']}")

print(f"\n✅ All {len(results)} emails valid: no numbers, same display name, all unique")