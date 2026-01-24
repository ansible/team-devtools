#!/usr/bin/env python3
#
# Simplified BSD License https://opensource.org/licenses/BSD-2-Clause)
#

from jira import JIRA
import yaml
import sys
import argparse
import os
import csv


PRIORITIES = ['Critical', 'Major', 'Normal', 'Minor']
ISSUE_TYPES = ['Task', 'Story', 'Spike', 'Bug', 'Epic']
AFFECTS_VERSIONS = ['2.4', '2.5', '2.6', 'aap-devel']


def load_config():
    """Load Jira configuration from config file"""
    with open('config') as f:
        """
        config is a file that contains these keys:
        jira_token: personal access token
        jira_server: https://jira.example.com
        """
        config = yaml.safe_load(f)
    return config


def load_template(filename):
    """Load text from a template file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, filename)
    
    try:
        with open(template_path, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Warning: Template file '{filename}' not found. Using default value '.'")
        return '.'


def get_component(jiraconn, project, component_name):
    """Get component object by name"""
    prj_components = jiraconn.project_components(project=project)
    for comp in prj_components:
        if comp.name == component_name:
            return comp
    raise ValueError(f"Component '{component_name}' not found in project {project}")


def select_from_list(prompt, options, default=None, validator=None):
    """Display numbered options and get user selection (0-based indexing)"""
    print(f"\n{prompt}")
    for i, option in enumerate(options):
        default_marker = " (default)" if default and option == default else ""
        print(f"  {i}. {option}{default_marker}")
    
    default_index = options.index(default) if default else None
    prompt_text = f"Select [0-{len(options)-1}]"
    if default_index is not None:
        prompt_text += f" [default: {default_index}]"
    
    while True:
        user_input = input(f"{prompt_text}: ").strip()
        
        if not user_input and default:
            return default
        
        try:
            return validator(user_input)
        except argparse.ArgumentTypeError as e:
            print(f"Error: {e}")


def parse_index_or_name(value, options, field_name):
    """Convert index or name to option name"""
    if value.isdigit():
        index = int(value)
        if 0 <= index < len(options):
            return options[index]
        raise argparse.ArgumentTypeError(f"{field_name} index must be 0-{len(options)-1}")
    elif value in options:
        return value
    else:
        raise argparse.ArgumentTypeError(f"Invalid {field_name}. Use 0-{len(options)-1} or {', '.join(options)}")


def parse_priority(value):
    """Convert priority index or name to priority name"""
    return parse_index_or_name(value, PRIORITIES, "priority")


def parse_issue_type(value):
    """Convert issue type index or name to issue type name"""
    return parse_index_or_name(value, ISSUE_TYPES, "issue type")


def parse_affects_version(value):
    """Convert affects version index or name to version string"""
    return parse_index_or_name(value, AFFECTS_VERSIONS, "affects version")


def create_issues_from_csv(jiraconn, csv_file, config):
    """
    Create multiple issues from a CSV file
    
    CSV format:
        summary,priority,issue_type,epic_link,affects_version,description_file,acceptance_criteria_file
    
    Required columns: summary
    Optional columns: priority, issue_type, epic_link, affects_version, description_file, acceptance_criteria_file
    """
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            
            # Validate required columns
            if 'summary' not in reader.fieldnames:
                print("Error: CSV must have a 'summary' column")
                sys.exit(1)
            
            issues_created = []
            issues_failed = []
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                summary = row.get('summary', '').strip()
                if not summary:
                    print(f"Row {row_num}: Skipping - no summary")
                    continue
                
                # Parse and validate priority (use default if not provided or invalid)
                priority_str = row.get('priority', '').strip()
                if priority_str:
                    try:
                        priority = parse_priority(priority_str)
                    except argparse.ArgumentTypeError as e:
                        print(f"Row {row_num}: Invalid priority '{priority_str}', using default 'Normal'. Error: {e}")
                        priority = 'Normal'
                else:
                    priority = 'Normal'
                
                # Parse and validate issue type (use default if not provided or invalid)
                issue_type_str = row.get('issue_type', '').strip()
                if issue_type_str:
                    try:
                        issue_type = parse_issue_type(issue_type_str)
                    except argparse.ArgumentTypeError as e:
                        print(f"Row {row_num}: Invalid issue_type '{issue_type_str}', using default 'Task'. Error: {e}")
                        issue_type = 'Task'
                else:
                    issue_type = 'Task'
                
                # Optional fields
                epic_link = row.get('epic_link', '').strip() or None
                affects_version_str = row.get('affects_version', '').strip()
                
                # Validate affects_version
                affects_version = None
                if affects_version_str:
                    if issue_type != 'Bug':
                        print(f"Row {row_num}: Warning - affects_version '{affects_version_str}' ignored (only valid for Bug issue type, not '{issue_type}')")
                    else:
                        try:
                            affects_version = parse_affects_version(affects_version_str)
                        except argparse.ArgumentTypeError as e:
                            print(f"Row {row_num}: Invalid affects_version '{affects_version_str}', skipping. Error: {e}")
                            affects_version = None
                
                description_file = row.get('description_file', '').strip() or 'description.txt'
                acceptance_criteria_file = row.get('acceptance_criteria_file', '').strip() or 'acceptance_criteria.txt'
                
                print(f"\nRow {row_num}: Creating issue '{summary}'...")
                try:
                    issue = create_aap_issue(
                        jiraconn=jiraconn,
                        summary=summary,
                        priority=priority,
                        issue_type=issue_type,
                        epic_link=epic_link,
                        affects_version=affects_version,
                        description_file=description_file,
                        acceptance_criteria_file=acceptance_criteria_file
                    )
                    issue_url = f"{config['jira_server']}/browse/{issue.key}"
                    issues_created.append((row_num, issue.key, summary, issue_url))
                except Exception as e:
                    print(f"Row {row_num}: Failed to create issue - {e}")
                    issues_failed.append((row_num, summary, str(e)))
            
            # Summary
            print("\n" + "="*60)
            print("Batch creation complete!")
            print(f"✓ Created: {len(issues_created)} issues")
            if issues_failed:
                print(f"✗ Failed: {len(issues_failed)} issues")
            print("="*60)
            
            if issues_created:
                print("\nSuccessfully created issues:")
                for row_num, key, summary, url in issues_created:
                    print(f"  Row {row_num}: {key} - {summary}")
                    print(f"             {url}")
            
            if issues_failed:
                print("\nFailed to create issues:")
                for row_num, summary, error in issues_failed:
                    print(f"  Row {row_num}: {summary} - {error}")
            
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        sys.exit(1)


def create_aap_issue(jiraconn, summary, priority='Normal', issue_type='Task', epic_link=None, affects_version=None, description_file='description.txt', acceptance_criteria_file='acceptance_criteria.txt'):
    """
    Create an issue in the AAP project
    
    Args:
        jiraconn: JIRA connection object
        summary: Issue summary/title
        priority: Priority name (e.g., 'Critical', 'Major', 'Normal', 'Minor'), default: 'Normal'
        issue_type: Issue type (e.g., 'Task', 'Story', 'Spike', 'Bug', 'Epic'), default: 'Task'
        epic_link: Epic link ID (e.g., 'AAP-123'), optional
        affects_version: Affects Version (for bugs), optional
        description_file: Path to description template file
        acceptance_criteria_file: Path to acceptance criteria template file
    """
    # Validate: affects_version can only be used with Bug issue type
    if affects_version and issue_type != 'Bug':
        raise ValueError(f"affects_version can only be specified for Bug issue types, not '{issue_type}'")
    
    # Load templates from files
    description = load_template(description_file)
    acceptance_criteria = load_template(acceptance_criteria_file)
    
    # Get the dev-tools component
    try:
        component = get_component(jiraconn, 'AAP', 'dev-tools')
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    issue_template = {
        'project': 'AAP',
        'summary': summary,
        'description': description,
        'issuetype': {'name': issue_type},
        'components': [{'name': component.name}],
        'priority': {'name': priority},
        'customfield_12319275': [{'value': 'Dev Tools'}],  # Workstream (array format)
        'customfield_12315940': acceptance_criteria,  # Acceptance Criteria
    }
    
    # Add Epic Link only if provided
    if epic_link:
        issue_template['customfield_12311140'] = epic_link
    
    # Add Affects Version only if provided (typically for bugs)
    if affects_version:
        issue_template['versions'] = [{'name': affects_version}]
    
    try:
        issue = jiraconn.create_issue(fields=issue_template)
        print(f"✓ Issue created successfully: {issue.key}")
        print(f"  URL: {jiraconn.server_url}/browse/{issue.key}")
        return issue
    except Exception as e:
        print(f"Error creating issue: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Create AAP Jira issues with dev-tools component',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s -s "Implement new feature" -p Major -e AAP-100
  %(prog)s -s "Fix bug" -p Critical -e AAP-100
  %(prog)s --interactive
  %(prog)s -s "Custom template" -d custom_desc.txt -a custom_ac.txt
  %(prog)s -b issues.csv
  
Batch CSV format (required: summary; optional: priority, issue_type, epic_link, affects_version, 
description_file, acceptance_criteria_file):
  summary,priority,issue_type,epic_link,affects_version
  "Fix login bug",Critical,Bug,AAP-100,2.5
  "Add dark mode",Normal,Task,AAP-101,
  
Affects Version options (ONLY for bugs): 0=2.4, 1=2.5, 2=2.6, 3=aap-devel
  
Note: Description and Acceptance Criteria are loaded from template files.
      Default files: description.txt and acceptance_criteria.txt
      Override with -d/--description-file and -a/--acceptance-criteria-file
        '''
    )
    
    parser.add_argument('-s', '--summary', 
                       help='Issue summary/title')
    parser.add_argument('-p', '--priority', 
                       type=parse_priority,
                       help='Issue priority: 0=Critical, 1=Major, 2=Normal, 3=Minor (default: Normal)')
    parser.add_argument('-t', '--issue-type',
                       type=parse_issue_type,
                       help='Issue type: 0=Task, 1=Story, 2=Spike, 3=Bug, 4=Epic (default: Task)')
    parser.add_argument('-e', '--epic-link',
                       help='Epic Link (e.g., AAP-123) - optional')
    parser.add_argument('-v', '--affects-version',
                       type=parse_affects_version,
                       help='Affects Version: 0=2.4, 1=2.5, 2=2.6, 3=aap-devel (ONLY for bugs) - optional')
    parser.add_argument('-d', '--description-file',
                       default='description.txt',
                       help='Path to description template file (default: description.txt)')
    parser.add_argument('-a', '--acceptance-criteria-file',
                       default='acceptance_criteria.txt',
                       help='Path to acceptance criteria template file (default: acceptance_criteria.txt)')
    parser.add_argument('-b', '--batch-file',
                       help='CSV file with multiple issues to create (batch mode)')
    parser.add_argument('-i', '--interactive', 
                       action='store_true',
                       help='Run in interactive mode')
    
    args = parser.parse_args()
    
    # Load configuration
    try:
        config = load_config()
        jiraconn = JIRA(token_auth=config['jira_token'], server=config['jira_server'])
    except FileNotFoundError:
        print("Error: config file not found. Please create a config file with jira_token and jira_server.")
        sys.exit(1)
    except KeyError as e:
        print(f"Error: Missing key in config file: {e}")
        sys.exit(1)
    
    # Batch mode - create issues from CSV
    if args.batch_file:
        create_issues_from_csv(jiraconn, args.batch_file, config)
        return
    
    # Interactive mode - always prompt unless explicitly provided via CLI
    if args.interactive or not args.summary:
        print("=== AAP Issue Creation (Interactive Mode) ===\n")
        
        summary = args.summary or input("Issue Summary: ").strip()
        if not summary:
            print("Error: Summary is required")
            sys.exit(1)
        
        # Only prompt if not explicitly provided on command line
        if args.priority is not None:
            priority = args.priority
        else:
            priority = select_from_list("Select Priority:", PRIORITIES, default='Normal', validator=parse_priority)
        
        if args.issue_type is not None:
            issue_type = args.issue_type
        else:
            issue_type = select_from_list("Select Issue Type:", ISSUE_TYPES, default='Task', validator=parse_issue_type)
        
        epic_link = args.epic_link or input("Epic Link (e.g., AAP-123) [optional, press Enter to skip]: ").strip()
        
        # Only prompt for affects_version if issue type is Bug
        if issue_type == 'Bug':
            if args.affects_version is not None:
                affects_version = args.affects_version
            else:
                affects_version = select_from_list("Select Affects Version:", AFFECTS_VERSIONS, default=None, validator=parse_affects_version)
                if not affects_version:  # User pressed Enter without selecting
                    affects_version = None
        else:
            if args.affects_version:
                print(f"Warning: affects_version ignored (only valid for Bug issue type, not '{issue_type}')")
            affects_version = None
        
        print("\n--- Creating issue with the following details ---")
        print(f"Summary: {summary}")
        print(f"Issue Type: {issue_type}")
        print(f"Priority: {priority}")
        print(f"Epic Link: {epic_link if epic_link else '(none)'}")
        if issue_type == 'Bug':
            print(f"Affects Version: {affects_version if affects_version else '(none)'}")
        print(f"Description: {load_template(args.description_file)}")
        print(f"Acceptance Criteria: {load_template(args.acceptance_criteria_file)}")
        print()
        
        confirm = input("Create this issue? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Cancelled.")
            sys.exit(0)
    else:
        # Non-interactive mode - use parsed arguments directly (with defaults)
        summary = args.summary
        priority = args.priority if args.priority else 'Normal'
        issue_type = args.issue_type if args.issue_type else 'Task'
        epic_link = args.epic_link
        affects_version = args.affects_version
    
    # Create the issue
    create_aap_issue(
        jiraconn=jiraconn,
        summary=summary,
        priority=priority,
        issue_type=issue_type,
        epic_link=epic_link,
        affects_version=affects_version,
        description_file=args.description_file,
        acceptance_criteria_file=args.acceptance_criteria_file
    )


if __name__ == '__main__':
    main()
