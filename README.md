# unknown-cogs

Custom cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) (V3).

---

## Installation

### Prerequisites
- Red-DiscordBot version `3.5.10` or higher
- Python `3.10` or higher

### Adding the Repository
Add this repository to your Red bot instance:
```ini
[p]repo add unknown-cogs https://github.com/Coltuna/unknown-cogs
```
*(Replace `[p]` with your bot's prefix.)*

### Installing Cogs
Install the desired cog(s):
```ini
[p]cog install unknown-cogs decancer
[p]cog install unknown-cogs selfrole
```

### Loading Cogs
Load the installed cog(s):
```ini
[p]load decancer
[p]load selfrole
```

---

## Available Cogs

### 1. Decancer
Remove cancerous and special characters or zalgo text from usernames and nicknames. Integrates directly with Red's native `modlog` system.

- **Commands:**
  - `[p]decancer [target]` (Aliases: `[p]dehoist`):
    - Target a specific **member** to decancer their nickname immediately.
    - Target a **role** (or leave empty for all server members) to batch-decancer all matching members after a confirmation prompt.
  - `[p]decancerset auto [true|false]`: Toggle automatic decancering for newly joined members.
  - `[p]decancerset defaultname <name>`: Set the fallback nickname (or `random`) when a nickname cannot be decancered.
  - `[p]decancerset showsettings`: View current Decancer configuration for the guild.

---

### 2. SelfRole
A sleek self-assignable role system designed with Discord Slash Commands for end users and text commands for administrators.

- **User Commands (Slash Commands):**
  - `/selfrole add <role>`: Add a self-assignable role to yourself.
  - `/selfrole remove <role>`: Remove a self-assignable role from yourself.
  - `/selfrole list`: View all currently available self-assignable roles.

- **Admin Commands (Prefix Text Commands):**
  - `[p]selfroleset add <role>`: Add a role to the list of self-assignable roles.
  - `[p]selfroleset remove <role|role_id>`: Remove a role from the self-assignable roles list (supports role ID in case a role was already deleted).
  - `[p]selfroleset allow_dangerous_role <true|false>`: Enable or disable allowing roles with elevated permissions to be made self-assignable (Guild Owner / Admin only).
  - `[p]selfroleset list`: View the configured self-assignable roles and dangerous role status.

---

## Support & Contributions

If you find any bugs or have feature requests, please open an issue on the repository.
