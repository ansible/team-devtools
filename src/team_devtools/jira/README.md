# AAP Jira Issue Creator

Automated script to create Jira issues in the AAP (Ansible Automation Platform) project with standardized templates and validation.

## Features

- **Three Modes**: Interactive, CLI, and CSV batch processing
- **Input Validation**: Validates priorities, issue types, and affects versions
- **Template Support**: Customizable description and acceptance criteria templates
- **Index or Name Selection**: Use numeric indices (0-4) or full names
- **Batch Processing**: Create multiple issues from CSV file
- **Bug Support**: Special handling for affects_version field (bugs only)

## Prerequisites

This tool requires the `jira` dependency group. Install it using:

```bash
uv sync --group jira
```

Or if working in the repository root:

```bash
uv pip install jira pyyaml pygithub
```

## Configuration

Create a `jira-config` file in the `resources/` directory (or copy and customize the example):

```bash
cd src/team_devtools/jira/resources
cp jira-config.example jira-config
# Edit jira-config with your credentials
```

The `jira-config` file should contain:

```yaml
# Jira Configuration File

jira_token: YOUR_PERSONAL_ACCESS_TOKEN
jira_server: https://issues.redhat.com
```

**Note**: The `jira-config` file is gitignored and should not be committed to version control.

To get a Jira personal access token:
1. Go to your Jira instance (e.g., https://issues.redhat.com)
2. Navigate to Profile → Personal Access Tokens
3. Create a new token and copy it

## Template Files

The script uses template files located in the `resources/` directory:

### `resources/description.txt`
Default template for issue descriptions. Supports Jira Wiki Markup formatting.

### `resources/acceptance_criteria.txt`
Default template for acceptance criteria.

Both files can be overridden per issue using `-d` and `-a` flags (with custom file paths), or via CSV columns.

## Usage Modes

### 1. Interactive Mode

Prompts for all required fields with guided selection menus.

```bash
./create_aap_issue.py --interactive
```

Or simply run without arguments (enters interactive mode if summary not provided):

```bash
./create_aap_issue.py
```

**Interactive Features:**
- Numbered selection menus for priority, issue type, and affects version
- Default values highlighted
- Confirmation screen before creating issue

### 2. Command-Line Mode

Specify all fields as command-line arguments.

```bash
./create_aap_issue.py -s "Fix login bug" -p Critical -t Bug -e AAP-100 -v 2.5
```

**Minimal example (uses defaults):**
```bash
./create_aap_issue.py -s "Add new feature"
# Uses: Priority=Normal, Type=Task
```

### 3. Batch CSV Mode

Create multiple issues from a CSV file.

```bash
./create_aap_issue.py -b issues.csv
```

**CSV Format:**

Required columns: `summary`, `affects_version` (Bug type **only**)

Optional columns: `priority` (default: Normal), `issue_type` (default: Task), `component` (default: dev-tools), `epic_link` (default: _None_), `description_file` (default: description.txt), `acceptance_criteria_file` (default: acceptance_criteria.txt)

**Example CSV:**

See `resources/issues_example.csv` for a complete example.

```csv
summary,priority,issue_type,component,epic_link,affects_version,description_file,acceptance_criteria_file
"Fix login authentication bug",Critical,Bug,dev-tools,AAP-100,2.5,,
"Add dark mode support",Normal,Task,vscode-plugin,AAP-101,,,
"Refactor auth module",1,Task,0,AAP-100,,,
"Setup CI/CD pipeline",0,2,1,AAP-102,,,
```

**Batch Features:**
- Non-blocking: One failure doesn't stop others
- Progress tracking with row numbers
- Summary report at the end (created vs failed)
- Validation warnings for invalid values

## Command-Line Arguments

| Flag | Long Form | Description | Default |
|------|-----------|-------------|---------|
| `-s` | `--summary` | Issue summary/title | (required) |
| `-p` | `--priority` | Issue priority (0-3 or name) | Normal |
| `-t` | `--issue-type` | Issue type (0-4 or name) | Task |
| `-c` | `--component` | Component (0-1 or name) | dev-tools |
| `-e` | `--epic-link` | Epic Link ID (e.g., AAP-123) | None |
| `-v` | `--affects-version` | Affects Version (bugs only, 0-3 or name) | None |
| `-d` | `--description-file` | Path to description template | resources/description.txt |
| `-a` | `--acceptance-criteria-file` | Path to acceptance criteria template | resources/acceptance_criteria.txt |
| `-b` | `--batch-file` | CSV file for batch creation | None |
| `-i` | `--interactive` | Force interactive mode | False |

## Field Options and Validation

### Priority (0-3)
- `0` = Critical
- `1` = Major
- `2` = Normal (default)
- `3` = Minor

### Issue Type (0-4)
- `0` = Task (default)
- `1` = Story
- `2` = Spike
- `3` = Bug
- `4` = Epic

### Component (0-1)
- `0` = dev-tools (default)
- `1` = vscode-plugin

### Affects Version (0-3, **ONLY for bugs**)
- `0` = 2.4
- `1` = 2.5
- `2` = 2.6
- `3` = aap-devel

**Important:** The `affects_version` field can ONLY be used with Bug issue types. Using it with other types will result in a warning and the value will be ignored.

## Examples

### Interactive Mode Examples

**Basic interactive:**
```bash
./create_aap_issue.py --interactive
```

**Interactive with pre-filled values:**
```bash
./create_aap_issue.py --interactive -p Critical -t Bug
# Will skip prompts for priority and issue type
```

### CLI Mode Examples

**Create a bug with all fields:**
```bash
./create_aap_issue.py \
  -s "Fix login authentication timeout" \
  -p Critical \
  -t Bug \
  -e AAP-100 \
  -v 2.5
```

**Using indices instead of names:**
```bash
./create_aap_issue.py -s "Add feature" -p 1 -t 0 -e AAP-100
# Priority: 1=Major, Type: 0=Task
```

**With custom templates:**
```bash
./create_aap_issue.py \
  -s "Security update" \
  -p Critical \
  -t Task \
  -d security_desc.txt \
  -a security_ac.txt
```

**Create a task (minimal):**
```bash
./create_aap_issue.py -s "Update documentation"
# Uses defaults: Normal priority, Task type
```

### Batch CSV Mode Examples

**Basic batch creation:**
```bash
./create_aap_issue.py -b my_issues.csv
```

**Sample CSV content:**
```csv
summary,priority,issue_type,epic_link,affects_version
"Critical security fix",0,3,AAP-100,2.5
"Implement feature X",2,0,AAP-101,
"Refactor module Y",1,0,AAP-100,
"Research spike for Z",2,2,AAP-102,
```

**Mixed index and name values:**
```csv
summary,priority,issue_type,epic_link,affects_version
"Bug fix",Critical,Bug,AAP-100,2.5
"Task item",1,Task,AAP-101,
"Story item",Major,Story,AAP-102,
```

## Output

### Single Issue Creation
```
✓ Issue created successfully: AAP-12345
  URL: https://issues.redhat.com/browse/AAP-12345
```

### Batch Creation Summary
```
============================================================
Batch creation complete!
✓ Created: 8 issues
✗ Failed: 2 issues
============================================================

Successfully created issues:
  Row 2: AAP-12345 - Fix login bug
  Row 3: AAP-12346 - Add dark mode
  ...

Failed to create issues:
  Row 5: Bad issue - Invalid priority value
  Row 7: Another issue - Missing required field
```

## Automated Fields

The following fields are automatically set for all issues:

- **Project:** AAP
- **Component:** Selectable (dev-tools or vscode-plugin, default: dev-tools)
- **Workstream:** Dev Tools (automatically set)
- **Description:** Loaded from template file
- **Acceptance Criteria:** Loaded from template file

## Error Handling

- **Invalid values in CLI:** Script exits with error message
- **Invalid values in CSV:** Row is skipped with warning, processing continues
- **Missing required fields:** Error message, row skipped (CSV) or exit (CLI)
- **Jira API errors:** Detailed error message with response details

## Troubleshooting

### "ModuleNotFoundError: No module named 'jira'"
Install required dependencies:
```bash
pip install -r requirements.txt
```

### "Error: config file not found"
Create a `config` file with your Jira credentials (see Configuration section).

### "affects_version ignored" warning
The affects_version field can only be used with Bug issue types. Remove it or change the issue type to Bug.

### CSV import fails
- Ensure CSV has a `summary` column header
- Check for proper CSV formatting (quoted fields with commas)
- Verify column names match exactly (case-sensitive)

## Tips and Best Practices

1. **Use interactive mode** when creating single issues - it's faster and provides validation
2. **Use batch CSV mode** for bulk creation - great for new epic creation
3. **Create custom templates** for different issue types (bugs vs features)
4. **Use numeric indices** in CSV for faster data entry (0-4 vs typing "Critical")
5. **Test with `--interactive`** before running batch CSV to verify configuration
6. **Keep template files** in sync with team standards

## Support

For issues or questions, contact your Jira administrator or create an issue in your team's issue tracker.
