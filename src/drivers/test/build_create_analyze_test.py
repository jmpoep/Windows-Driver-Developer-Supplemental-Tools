try:
    from multiprocessing.pool import ThreadPool
    import os
    import sys
    import subprocess
    import shutil
    import threading
    import time
    import fnmatch
    from sarif import loader 
    import pandas as pd
    from datetime import datetime
    import re
    import itertools
    from itertools import permutations
    import openpyxl # Not directly used but this will make sure it is installed
    import argparse

except ImportError as e:
    print("Import error: " + str(e) + "\nPlease install the required modules using pip install -r requirements.txt")
    exit(1)


print_mutex = threading.Lock()
health_df = pd.DataFrame()
detailed_health_df = pd.DataFrame()


def print_conditionally(*message):
    """
    Prints the message if the verbose flag is set.

    Args:
        message (str): The message to be printed.

    Returns:
        None
    """
    if args.verbose:
        for m in message:
            print(m, end=" ")
        print("")

# Any attributes specific to a test should be added to this class
# This also allows for things to be conditionally added to the test call, such as the UseNTIFS parameter
class ql_test_attributes:
    """
    Represents the attributes for a CodeQL test.

    Attributes:
        use_cpp (bool): Indicates whether to use C++ for the test.
        use_ntifs (bool): Indicates whether to use NTIFS for the test.
        template (str): The template for the test.
        path (str): The path for the test.
        ql_file (str): The CodeQL file for the test.
        ql_name (str): The name of the CodeQL test.
        ql_type (str): The type of the CodeQL test.
        ql_location (str): The location of the CodeQL test.
        no_attributes (bool): Indicates whether the test has attributes. External drivers do not have attributes.
    """

    def __init__(self, external_drivers=[], no_attributes=False, use_cpp=False, use_ntifs=False, template="", path="", ql_file="", ql_name="", ql_type="", ql_location=""):
        self.use_ntifs = use_ntifs
        self.template = template
        self.path = path
        self.ql_file = ql_file
        self.ql_name = ql_name
        self.ql_type = ql_type
        self.ql_location = ql_location
        self.use_cpp = use_cpp
        self.no_attributes = no_attributes
        self.output_file = ""
    def get_use_cpp(self):
        return self.use_cpp

    def set_use_cpp(self, use_cpp):
        self.use_cpp = use_cpp

    def get_use_ntifs(self):
        return self.use_ntifs
    def set_use_ntifs(self, use_ntifs):
        self.use_ntifs = use_ntifs

    def get_template(self):
        return self.template
    def set_template(self, template):
        self.template = template

    def get_path(self):
        return self.path
    def set_path(self, path):
        self.path = path

    def get_ql_file(self):
        return self.ql_file
    def set_ql_file(self, ql_file):
        self.ql_file = ql_file

    def get_ql_name(self):
        return self.ql_name
    def set_ql_name(self, ql_name):
        self.ql_name = ql_name

    def get_ql_type(self):
        return self.ql_type
    def set_ql_type(self, ql_type):
        self.ql_type = ql_type

    def get_ql_location(self):
        return self.ql_location

    def set_ql_location(self, ql_location):
        self.ql_location = ql_location
    
    def get_no_attributes(self):
        return self.no_attributes
    
    def set_no_attributes(self, no_attributes):
        self.no_attributes = no_attributes

    def get_external_drivers(self):
        return self.external_drivers

    def set_external_drivers(self, external_drivers):
        self.external_drivers = external_drivers
        
    # output sarif file 
    def set_output_file(self, output_file):
        self.output_file = output_file
    def get_output_file(self):
        return self.output_file

def get_git_root():
    """
    Returns the root directory of the Git repository.

    Returns:
        str: The root directory of the Git repository.
    """
    git_root = subprocess.Popen(['git', 'rev-parse', '--show-toplevel'], stdout=subprocess.PIPE).communicate()[0].rstrip().decode('utf-8')
    git_root = git_root.split('/')[-1]
    return git_root

def check_use_ntifs(ds_file):
    """
    Check if the given ds_file uses the ntifs.h header file.

    Args:
        ds_file (str): The path to the file to be checked.

    Returns:
        bool: True if the ntifs.h header file is found, False otherwise.
    """
    file = open(ds_file, "r")
    lines = file.readlines()
    for line in lines:
        if "ntifs.h" in line:
            file.close()
            return True
    file.close()
    return False

def find_ql_test_paths(directory, extension):
    """
    Walks through the specified directory and returns a dictionary mapping file paths to QL test attributes.

    Args:
        directory (str): The directory to walk through.
        extension (str): The file extension to filter files by.

    Returns:
        dict: A dictionary mapping file paths to QL test attributes.
    """
    
    ql_files_map = {}
    for root, dirs, files in os.walk(directory):
        # exclude wfp folder until correct test template is added
        ignore_paths = ["wfp", "QueryTemplate", "TestTemplate", ".vs"]
        root = root.replace("\\", "/")
        if any(path in ignore_paths for path in root.split("/")): 
            print_conditionally("Skipping: " + root)
            continue
        if "TestTemplate" in root:
            print_conditionally("Skipping: " + root)
            continue
        if fnmatch.filter(files, "driver_snippet.*"):
            use_ntifs = check_use_ntifs(os.path.join(root, fnmatch.filter(files, "driver_snippet.*")[0]))
            for file in files:
                if file.endswith(extension):
                    use_cpp = all([".cpp" in x for x in fnmatch.filter(files, "driver_snippet.c*")] or 
                                    [".hpp" in x for x in fnmatch.filter(files, "driver_snippet.c*")])
                    ql_obj = ql_test_attributes(use_ntifs=use_ntifs, use_cpp=use_cpp)
                    ql_obj.set_use_cpp(use_cpp)
                    ql_files_map[os.path.join(root, file)] = ql_obj
                    print_conditionally("Found: " + os.path.join(root, file))

    return ql_files_map


def find_project_configs(sln_files):
    """
    Find project configurations and platforms from a list of solution files.

    Args:
        sln_files (list): List of solution file paths.

    Returns:
        dict: A dictionary where the keys are solution file paths and the values are sets of configuration-platform tuples.
              Each tuple represents a project configuration and platform found in the solution file.
              If no configurations or platforms are found in a solution file, None is returned for that file.
    """
    configs_dict = {}
    for sln_file in sln_files:
        configs = set()
        with open(sln_file, "r") as file:
            content = file.read()
            match = re.search(r"\s*GlobalSection\(SolutionConfigurationPlatforms\).*", content)
            if match:
                lines = content[match.end():]
                end_index = lines.find("EndGlobalSection")
                if end_index != -1:
                    lines = lines[:end_index]
                    lines = lines.split("\n")
                    lines = [x for x in lines if x.strip() != ""]
                    for l in lines:
                        if "Debug" in l:
                            l = l[l.find("Debug"):]
                        if "Release" in l:
                            l = l[l.find("Release"):]
                        config = l.split("=")[0].strip().replace(" ", "").replace("\n", "").replace("\t", "").split('|')[0]
                        platform = l.split("=")[0].strip().replace(" ", "").replace("\n", "").replace("\t", "").split('|')[1]

                        
                        if platform in allowed_platforms:
                            if  args.debug_only and "Debug" not in config:
                                continue
                            if args.release_only and "Release" not in config:
                                continue
                            configs.add((config,platform))
                else:
                    print("No configurations or platforms found for " + sln_file)
                    return None
            else:
                print("No configurations or platforms found for " + sln_file)
                return None
        # Remove empty tuples from configs
        #configs = [c for c in configs if c]
        configs_dict[sln_file] = configs
    return configs_dict

                
def test_setup_external_drivers(sln_files):
    """
    Builds and sets up external drivers for testing.

    Args:
        sln_files (list): List of solution files.

    Returns:
        dict: A dictionary containing the configurations for each solution file.
    """
    configs = find_project_configs(sln_files)
    if not args.no_build:
        for sln_file in configs.keys():
            workdir = sln_file.split("\\")[:-1]
            workdir = "\\".join(workdir)
            
            # TODO make this multi threaded
            for config, platform in configs[sln_file]:
                print_conditionally("Building: " + sln_file + " " + str(config) + " " + str(platform))
                    
                out = subprocess.run(["msbuild", sln_file, "-clp:Verbosity=m", "-t:clean,build", "-property:Configuration="+config,  "-property:Platform="+platform, "-p:TargetVersion=Windows10",  
                            "-p:SignToolWS=/fdws", "-p:DriverCFlagAddOn=/wd4996", "-noLogo"], shell=True, capture_output=no_output)
                if out.returncode != 0:
                    print("Error in msbuild: " + sln_file)
                    try:
                        print(out.stderr.decode())
                    except:
                        print(out.stderr)

    return configs

def test_setup(ql_test):
    """
    Set up the test environment for CodeQL analysis.

    Args:
        ql_test (object): An instance of the QLTest class.

    Returns:
        object: The result of the msbuild command.

    Raises:
        None

    """
    
    current_working_dir = os.path.join(g_test_dir, "working",ql_test.get_ql_name()+'\\')
   
    # if os.getcwd().split("\\")[-1] == "test":
    # else:
    
    if os.path.exists(current_working_dir.strip()):
        shutil.rmtree(current_working_dir)
    print_conditionally("Creating working directory: " + current_working_dir)
    shutil.copytree(ql_test.get_template(), current_working_dir)
    print_conditionally("Copying files to working directory: " + current_working_dir)
    test_file_loc = os.path.dirname(ql_test.get_ql_file())
    
    # Copy files to driver directory

    for file in os.listdir(test_file_loc):
        src = os.path.join(test_file_loc,file)
        if(ql_test.get_ql_type() == "apps"):
            dst = os.path.join(current_working_dir+"\\",file)
        else:
            dst = os.path.join(current_working_dir+"\\driver\\",file)
        print_conditionally("Copying file "+file + " from " + src + " to " +  dst)
        shutil.copyfile(src, dst)
   
    # Rebuild the project using msbuild
    if not args.no_build:
        print_conditionally("Building: " + ql_test.get_ql_name())
        out1 = subprocess.run(["msbuild", "/t:rebuild", "/p:platform=x64", "/p:UseNTIFS="+ql_test.get_use_ntifs()+""],cwd=current_working_dir, shell=True, capture_output=no_output  ) 
        if out1.returncode != 0:
            print("Error in msbuild: " + ql_test.get_ql_name())
            try:
                print(out1.stderr.decode())
            except:
                print(out1.stderr)

            return None
    else:
        out1 = True
        
    return out1


  
def db_create_for_external_driver(sln_file, config, platform):
    """
    Create a CodeQL database for an external driver.

    Args:
        sln_file (str): The path to the solution file.
        config (str): The configuration to build the driver with.
        platform (str): The platform to build the driver for.

    Returns:
        str: The path to the created CodeQL database, or None if an error occurred.
    """
    # TODO only run from test dir

    # TODO add database output location option 
    workdir = sln_file.split("\\")[:-1]
    workdir = "\\".join(workdir)
    if not os.path.exists(os.getcwd() + "\\dbs"):
        os.makedirs(os.getcwd() + "\\dbs")

    # TODO either clear these, ask for overwrite, or use a different name
    db_loc = os.getcwd() + "\\dbs\\"+sln_file.split("\\")[-1].replace(".sln", "")+"_"+config+"_"+platform
    print_conditionally("Creating database: ",  db_loc)
    out2 = subprocess.run([codeql_path, "database", "create", db_loc, "--overwrite", "-l", "cpp", "--source-root="+workdir,
                           "--command=msbuild "+ sln_file+ " -clp:Verbosity=m -t:clean,build -property:Configuration="+config+" -property:Platform="+platform + " -p:TargetVersion=Windows10 -p:SignToolWS=/fdws -p:DriverCFlagAddOn=/wd4996 -noLogo" ], 
            cwd=workdir, 
            shell=True, capture_output=no_output  )
    if out2.returncode != 0:
        print("Error in codeql database create: " + db_loc)
        try:
            print(out2.stderr.decode())
        except:
            print(out2.stderr)

        return None
    else:
        print_conditionally(".... done!")
    return db_loc


def create_codeql_test_database(ql_test):
    """
    Create a CodeQL database for the given ql_test.

    Args:
        ql_test (object): The ql_test object containing the necessary information.

    Returns:
        object: The output of the database creation process.

    Raises:
        None

    """
    # Create the CodeQL database
    test_db_dir = os.path.join(g_test_dir, "TestDB")
    os.makedirs(test_db_dir, exist_ok=True) 
    if os.path.exists(os.path.join(test_db_dir,ql_test.get_ql_name())):
        shutil.rmtree(os.path.join(test_db_dir,ql_test.get_ql_name()))
    
    source_dir=os.path.join(g_test_dir, "working\\"+ql_test.get_ql_name()+"\\")
    db_loc =   os.path.join(test_db_dir, ql_test.get_ql_name()+"\\")
    
    codeql_command = [codeql_path, "database", "create", "-l", "cpp", "-s", source_dir, "--threads=0", "-c", "msbuild /p:Platform=x64;UseNTIFS="+ql_test.get_use_ntifs()+ 
                           " /t:rebuild " + source_dir + ql_test.get_template().split("\\")[-1] + ".sln", db_loc]
    print_conditionally(" - Database location: " + db_loc)
    print_conditionally(" - Source directory: " + source_dir)
    print_conditionally(" - Command to run: " + str(codeql_command))
    out2 = subprocess.run(codeql_command,
                            shell=True, capture_output=no_output  ) 
    if out2.returncode != 0:
        print("Error in codeql database create: " + ql_test.get_ql_name())
        try:
            print("ERROR MESSAGE:", out2.stderr.decode()  )
        except:
            print("ERROR MESSAGE:", out2.stderr)

        return None
    return db_loc


def analyze_codeql_database(ql_test, db_path=None):
    """
    Analyzes the CodeQL database.

    Args:
        ql_test (object): The CodeQL test object.

    Returns:
        object: The result of the analysis.

    Raises:
        None

    """
    print_conditionally("Analyzing database: " + db_path)

    # Analyze the CodeQL database
    
    if db_path is not None: # When using external drivers, save databases in current directory
        database_loc = db_path
        if args.existing_database:
            if not os.path.exists(os.path.join(g_analysis_file_dir,ql_test.get_ql_name())): 
                os.makedirs(os.path.join(g_analysis_file_dir,ql_test.get_ql_name()), exist_ok=True)
            output_file = os.path.join(g_analysis_file_dir,ql_test.get_ql_name(), db_path.split('\\')[-1]+".sarif")
        else:
            output_file = os.path.join(g_analysis_file_dir,ql_test.get_ql_name()+".sarif")
        ql_test.set_output_file(output_file)
    else:
        print("No database path provided!")
        return None

    if args.use_codeql_repo:
        proc_command = [codeql_path, "database", "analyze", database_loc, "--format=sarifv2.1.0", "--output="+output_file,ql_test.get_ql_file(), "--additional-packs", args.use_codeql_repo, "--threads=0"]
    else:
        proc_command = [codeql_path, "database", "analyze", database_loc, "--format=sarifv2.1.0", "--output="+output_file, ql_test.get_ql_file(), "--threads=0"]
        
    print_conditionally("Sarif output location: " + output_file)
      
    out3 = subprocess.run(proc_command, 
                    shell=True, capture_output=no_output  ) 
        
    if out3.returncode != 0:
        print("Error in codeql database analyze: " + ql_test.get_ql_name())
        try:
            print(out3.stderr.decode()  )
        except:
            print(out3.stderr)
        return None

    return output_file


def sarif_diff(ql_test):
    """
    Perform SARIF diff between the generated SARIF file and the reference SARIF file.

    Args:
        ql_test: An instance of the QLTest class representing the test case.

    Returns:
        The output of the SARIF diff command if successful, None otherwise.
    """
    sarif_prev = os.path.join(ql_test.get_path(),ql_test.get_ql_name()+".sarif")
    sarif_new = ql_test.get_output_file()
    sarif_out = os.path.join(g_diff_dir, ql_test.get_ql_name()+".sarif")
    print_conditionally("Running sarif diff: " + ql_test.get_ql_name(), "\n - Previous: ", sarif_prev, "\n - New: ", sarif_new)
    out4 = subprocess.run(["sarif", "diff", "-o", sarif_out ,sarif_prev, sarif_new], 
                    shell=True, capture_output=no_output  ) 
    if out4.returncode != 0:
        print("Error in sarif diff: " + ql_test.get_ql_name())
        try:
            print(out4.stderr.decode()  )
        except:
            print(out4.stderr)
        return None
    print_conditionally("Diff output location:", sarif_out)

    return out4

def sarif_results(ql_test, sarif_file):
    """
    Retrieves SARIF results for a given QL test.

    Args:
        ql_test (QLTest): The QL test object.

    Returns:
        None
    """
    sarif_data = loader.load_sarif_file(sarif_file)
    return sarif_data.get_result_count_by_severity(), sarif_data.get_records()


def format_excel_results():
    """
    Formats the results Excel file.

    Args:
        None

    Returns:
        None
    """
    # TODO 
    pass

def run_test(ql_test):
    """
    Run a test for the given ql_test object.

    Args:
        ql_test: The ql_test object representing the test to be run.

    Returns:
        None
    """
  
    # Print test attributes
    print_mutex.acquire()
    print("\nRunning test: " + ql_test.get_ql_name())
    
    print_conditionally(" - Template: ", ql_test.get_template(), "\n",  
          "- Driver Framework: ", ql_test.get_ql_type(), "\n",  
          "- Query location: ", ql_test.get_ql_location(), "\n",  
          "- UseNTIFS flag: ", ql_test.get_use_ntifs())
    print_mutex.release()

    create_codeql_database_result = None
    if not args.existing_database:
        test_setup_result = test_setup(ql_test)
        if test_setup_result is None:
            print("Error setting up test: " + ql_test.get_ql_name(),"Skipping...")
            return None
        
        print_conditionally("Creating test database")
        create_codeql_database_result = create_codeql_test_database(ql_test)
        if create_codeql_database_result is None:
            print("Error creating database: " + ql_test.get_ql_name(),"Skipping...")
            return None
        else:
            db_path = create_codeql_database_result
    else:
        db_path=args.existing_database
        print_conditionally("Using existing database: " + db_path)

    if args.build_database_only:
        return None

    analyze_codeql_database_result = analyze_codeql_database(ql_test, db_path) # result is path to sarif file if successful
    if analyze_codeql_database_result is None:
        print("Error analyzing database: " + db_path,"Skipping...")
        return None

    if not args.existing_database:   
        sarif_diff_result = sarif_diff(ql_test)
        if sarif_diff_result is None: 
            print("Error running sarif diff: " + db_path,"Skipping...")
            return None
    
    return analyze_codeql_database_result


def parse_attributes(queries):
    """
    Parses the attributes of the queries and returns a list of query objects.

    Args:
        queries (dict): A dictionary containing the queries.

    Returns:
        list: A list of query objects.

    """
    query_objs = []
    for query in queries:
        if "working" in query or "TestDB" in query:
            continue
        path = os.path.normpath(query)
        ql_file = path

        path = path.split(os.sep)
        ql_name = path[-2]
        
        di = path.index("drivers")
        ql_type = path[di+1]

        template = g_template_dir
        if queries[query].get_use_cpp():
            template += "CppKMDFTestTemplate"
        elif(ql_type == "general"):
            template  += "WDMTestTemplate"
        elif(ql_type == "wdm"):
            template += "WDMTestTemplate"
        elif(ql_type == "kmdf"):
            template += "KMDFTestTemplate"
        elif(ql_type == "apps"):
            template += "ApplicationForDriversTestTemplate"
        else:
            pass
        
        if args.override_template:
            template = args.override_template

        if queries[query].get_use_ntifs():
            use_ntifs = "1" 
        else:
            use_ntifs = "0"
        
        ql_location = "/".join(path[path.index(ql_type)+1:path.index(ql_name)])
        queries[query].set_use_ntifs(use_ntifs)
        queries[query].set_template(template)
        queries[query].set_path(os.path.dirname("/".join(path)))
        queries[query].set_ql_file(ql_file)
        queries[query].set_ql_name(ql_name)
        queries[query].set_ql_type(ql_type)
        queries[query].set_ql_location(ql_location)
        query_objs.append(queries[query])
    return query_objs


def run_tests_external_drivers(ql_tests_dict):
    """
    Runs tests on external drivers.

    Args:
        ql_tests_dict (dict): A dictionary containing the QL tests to be executed.

    Returns:
        None
    """
    df_column_names = []
    for ql_test in ql_tests_dict:
        df_column_names.append(ql_test.split("\\")[-1].replace(".ql", ""))
    
    # Only need to setup external drivers once
    configs = test_setup_external_drivers(driver_sln_files)
    created_databases = []
    if configs is None:
        return    
    total = len(configs.keys())
    count = 0
    if args.existing_database:
            print_conditionally("Using existing database: " + args.existing_database)
            folder_names = [os.path.join(args.existing_database, name) for name in os.listdir(args.existing_database) if os.path.isdir(os.path.join(args.existing_database, name))]
            created_databases = folder_names
            total = len(folder_names)
    else:
        for sln_file in configs.keys():
            print_conditionally("Creating databases for " + sln_file + " ---> " + str(count) + "/" + str(total))
            for config, platform in configs[sln_file]:
                create_codeql_database_result = db_create_for_external_driver(sln_file, config, platform)
                if create_codeql_database_result is None: 
                    print("Error creating database for " + sln_file + " " + config + " " + platform + " skipping...")
                    continue 
                else:
                    if create_codeql_database_result in created_databases:
                        print("Database already created!  " + create_codeql_database_result)
                    created_databases.append(create_codeql_database_result)
            count += 1
    # Analyze created databses
    if not args.build_database_only:
        return
    
    ql_tests_with_attributes = parse_attributes(ql_tests_dict)
    count = 0
    total = len(created_databases)*len(ql_tests_with_attributes)
    for ql_test in ql_tests_with_attributes:
        print_conditionally("Run query: " + ql_test.get_ql_name())
        for db in created_databases:
            print_conditionally("...... on database " + str(count) + "/" + str(total)+ ": " + db)
            count += 1
            try:
                result_sarif = analyze_codeql_database(ql_test, db)
            except Exception as e:
                print("Error analyzing database: " + db, e)
                continue
            try:
                if result_sarif is None:
                    continue
                analysis_results, detailed_analysis_results = sarif_results(ql_test, result_sarif)
            except Exception as e:
                print("Error getting sarif results: " + db, e)
                continue
            health_df.at[db.split("\\")[-1], ql_test.get_ql_name()] = str(analysis_results['error'] + analysis_results['warning'] + analysis_results['note'])
            detailed_health_df.at[db.split("\\")[-1], ql_test.get_ql_name()] = str(detailed_analysis_results)
    # save results
    result_file = "external_drivers_results.xlsx"
    with pd.ExcelWriter(result_file) as writer:
        health_df.to_excel(writer, sheet_name="Results")
        local_codeql_version_df.to_excel(writer, sheet_name="Local CodeQL Version")
        local_codeql_packs_df.to_excel(writer, sheet_name="Local CodeQL Packs")
        local_system_info_df.to_excel(writer, sheet_name="Local System Info")
    with pd.ExcelWriter("detailed" + result_file) as writer:
        detailed_health_df.to_excel(writer, sheet_name="Results")
        local_codeql_version_df.to_excel(writer, sheet_name="Local CodeQL Version")
        local_codeql_packs_df.to_excel(writer, sheet_name="Local CodeQL Packs")
        local_system_info_df.to_excel(writer, sheet_name="Local System Info")
    if args.compare_results:
        compare_health_results("detailed"+result_file)
    

def find_last_xlsx_file(curr_results_path):
    """
    Finds the most recent xlsx file in the current directory.
    Used for local storage of results.
    Args:
        None

    Returns:
        str: The path to the most recent xlsx file.
    """
    if "detailed" in curr_results_path:
        print("Comparing detailed results")
        detailed = True
    else:
        detailed = False

    files = os.listdir()
    files = [x for x in files if "diff" not in x]
    if detailed:
        files = [x for x in files if x.endswith(".xlsx") and "detailed" in x and x != curr_results_path]
    else:
        files = [x for x in files if x.endswith(".xlsx") and "detailed" not in x and x != curr_results_path]
    files.sort(key=os.path.getmtime, reverse=True)
    if len(files) == 0:
        return None
    return files[0]


def compare_health_results(curr_results_path):
    """
    Compares the health of test results to those from a previous run.

    Args:
        None

    Returns:
        None
    """
   
    prev_results = 'azure-'+curr_results_path 
            
    prev_results_df = pd.read_excel(prev_results, index_col=0, sheet_name=0) 
    prev_results_codeql_version_df = pd.read_excel(prev_results, index_col=0, sheet_name=1)
    prev_results_codeql_packs_df = pd.read_excel(prev_results, index_col=0, sheet_name=2)
    prev_results_local_system_info_df = pd.read_excel(prev_results, index_col=0, sheet_name=3)
    curr_results_df = pd.read_excel(curr_results_path, index_col=0, sheet_name=0)
    print_conditionally("Comparing results...")
    print_conditionally("Previous results: ", prev_results)
    print_conditionally("Current results: ", curr_results_path)
    for row in prev_results_df.index:
        if row not in curr_results_df.index:
            curr_results_df.loc[row] = None
            print_conditionally("Adding row to current results: ", row)
       
    for row in curr_results_df.index:
        if row not in prev_results_df.index:
            prev_results_df.loc[row] = None
            print_conditionally("Adding row to previous results: ", row)
   
    prev_results_df = prev_results_df.sort_index()
    curr_results_df = curr_results_df.sort_index()

    #TODO this is a tempoary fix for the issue with the backslashes in the results in codeql cli version 2.18.x+
    prev_results_df = prev_results_df.replace({r'\\': ''}, regex=True)
    curr_results_df = curr_results_df.replace({r'\\': ''}, regex=True)
            
    diff_results = curr_results_df.compare(prev_results_df, keep_shape=True, result_names=("Current", "Previous"))  
    
    if not all(diff_results.isnull().all()) :
        print("Differences found in results!")
        with pd.ExcelWriter("diff" + curr_results_path) as writer:
            diff_results.to_excel(writer, sheet_name="Diff")
            local_codeql_version_df.to_excel(writer, sheet_name="Local CodeQL Version")
            local_codeql_packs_df.to_excel(writer, sheet_name="Local CodeQL Packs")
            local_system_info_df.to_excel(writer, sheet_name="Local System Info")
            prev_results_codeql_version_df.to_excel(writer, sheet_name="Last Stored CodeQL Version")
            prev_results_codeql_packs_df.to_excel(writer, sheet_name="Last Stored CodeQL Packs")
            prev_results_local_system_info_df.to_excel(writer, sheet_name="Last Stored System Info")
        os.remove(prev_results)
    else:
        print("No differences found in results")
        os.remove(prev_results)
        exit(0)
    
def run_tests(ql_tests_dict):
    """
    Run the given CodeQL tests.

    Args:
        ql_tests_dict (dict): A dictionary containing the CodeQL tests.

    Returns:
        None
    """
    ql_tests_with_attributes = parse_attributes(ql_tests_dict)
    
    for ql_test in ql_tests_with_attributes:
        result_sarif = run_test(ql_test)
        if not args.build_database_only:
            if not result_sarif:
                print("Error running test: " + ql_test.get_ql_name(),"Skipping...")
                continue
            analysis_results, detailed_analysis_results = sarif_results(ql_test, result_sarif)
            health_df.at[ql_test.get_ql_name(), "Result"] = str(int(analysis_results['error'])+int(analysis_results['warning'])+int(analysis_results['note']))
            detailed_health_df.at[ql_test.get_ql_name(), "Result"] = str(detailed_analysis_results) 
      
    # save results
    result_file = "functiontestresults.xlsx"
    with pd.ExcelWriter(result_file) as writer:
        health_df.to_excel(writer, sheet_name="Results")
        local_codeql_version_df.to_excel(writer, sheet_name="Local CodeQL Version")
        local_codeql_packs_df.to_excel(writer, sheet_name="Local CodeQL Packs")
        local_system_info_df.to_excel(writer, sheet_name="Local System Info")
    with pd.ExcelWriter("detailed"+result_file) as writer:
        detailed_health_df.to_excel(writer, sheet_name="Results")
        local_codeql_version_df.to_excel(writer, sheet_name="Local CodeQL Version")
        local_codeql_packs_df.to_excel(writer, sheet_name="Local CodeQL Packs")
        local_system_info_df.to_excel(writer, sheet_name="Local System Info")
    if args.compare_results:
        compare_health_results("detailed"+result_file)
    
def find_g_template_dir(template):
    """
    Finds the directory of the given template.

    Args:
        template (str): The name of the template.

    Returns:
        str: The path to the template directory.
    """
    for root, dirs, files in os.walk(os.getcwd()):
        if template in dirs:
            return os.path.abspath(os.path.join(root, template) )+ "\\"
    return None


def find_sln_file(path):
    """
    Finds the solution file for the project.

    Args:
        None

    Returns:
        str: The path to the solution file.
    """
    sln_paths = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith(".sln"):
                sln_paths.append(os.path.join(root, file))
    return list(set(sln_paths))


if __name__ == "__main__":
    # Sys input flags
    parser = argparse.ArgumentParser(description='Build, create, and analyze CodeQL databases for testing queries. \
            Running this script without any flags will run all queries on their respective driver template project with\
            injected tests from driver_snippet.c')
    parser.add_argument('-e', '--external_drivers', help='Use external drivers at <path> for testing instead of drivers in the repo', type=str, required=False)
    parser.add_argument('-l', '--no_clean', help='Do not clean the working directory before running tests', action='store_true', required=False)
    parser.add_argument('-b', '--existing_database', help='Use existing database at <path> for testing instead of creating a new one', type=str, required=False)
    parser.add_argument('-d', '--debug_only', help='Debug only', action='store_true', required=False)
    parser.add_argument('-r', '--release_only', help='Release only', action='store_true', required=False)
    parser.add_argument('-n', '--no_build', help='Do not build the driver before running the test', action='store_true', required=False)
    parser.add_argument('-o', '--override_template', help='Override the template used for the test using <template>', type=str, required=False, choices=["CppKMDFTestTemplate", "KMDFTestTemplate", "WDMTestTemplate"])
    parser.add_argument('-v', '--verbose', help='verbose output on', action='store_true', required=False)
    parser.add_argument('--more_verbose', help='verbose output on including subprocess outputs', action='store_true', required=False)
    parser.add_argument('-c', '--use_codeql_repo', help='Use the codeql repo at <path> for the test instead of qlpack installed with CodeQL Package Manager', type=str, required=False)
    parser.add_argument('-i', '--individual_test', help='Run only the tests with <name> in the name', type=str, required=False)
    parser.add_argument('-m', '--compare_results', help='Compare results to previous run', action='store_true', required=False)
    parser.add_argument('--compare_results_no_build',help='Compare results to previous run',type=str,required=False,)
    parser.add_argument('--codeql_path', help='Path to the codeql executable',type=str,required=False,)
    parser.add_argument('--build_database_only', help='Build database only',action='store_true',required=False,)
    args = parser.parse_args()
           
    if args.codeql_path:
        codeql_path = args.codeql_path
    else:
        codeql_path = "codeql"

    codeql_version = subprocess.run([codeql_path, "version"], capture_output=True) # test codeql is working
    local_codeql_version_df = pd.DataFrame([x for x in codeql_version.stdout.decode().split('\n')])
    codeql_packs = subprocess.run([codeql_path, "resolve", "qlpacks"], capture_output=True) 
    local_codeql_packs_df = pd.DataFrame([x for x in codeql_packs.stdout.decode().split('\n')])
    system_info = subprocess.run(["systeminfo"], capture_output=True) 
    local_system_info_df = pd.DataFrame([x for x in system_info.stdout.decode().split('\n')])


    if args.compare_results_no_build:
        prev_results = "functiontestresults.xlsx"
        compare_health_results(args.compare_results_no_build)
        exit(0)

    allowed_platforms = ["x64", "x86", "ARM", "ARM64"]
    no_output = True
    start_time = time.time()

    if not args.no_clean and not args.existing_database:
        print_conditionally("Cleaning working directories: TestDB, working, AnalysisFiles")
        if os.path.exists("TestDB"):
            shutil.rmtree("TestDB")
        if os.path.exists("working"):
            shutil.rmtree("working")
        if os.path.exists("AnalysisFiles"):
            shutil.rmtree("AnalysisFiles")

    cwd = os.getcwd()
    path = os.path.normpath(cwd)
    path = path.split(os.sep)
    root_dir = get_git_root()
    
    dir_to_search ="/".join(path[0:path.index(root_dir)+1])
    extension_to_search = ".ql"
    
    ql_tests = find_ql_test_paths(dir_to_search,extension_to_search)
    g_template_dir = ''
    
    # find the template directory
    g_template_dir = find_g_template_dir("TestTemplates")
    if not g_template_dir:
        print_conditionally("Using default template directory: src\\drivers\\test\\TestTemplates\\")    
        g_template_dir = os.path.join(os.getcwd(), "src\\drivers\\test\\TestTemplates\\")
    print_conditionally("Using template directory: " + g_template_dir)
    
    g_diff_dir = os.path.normpath(os.path.join(g_template_dir, "..\\diff\\"))
    driver_sln_files = []
    
    g_test_dir = os.path.normpath(os.path.join(g_template_dir, "..\\"))
    g_analysis_file_dir = os.path.normpath(os.path.join(g_test_dir, "AnalysisFiles"))
    if not os.path.exists(g_analysis_file_dir):
        os.makedirs(g_analysis_file_dir, exist_ok=True) 
        
    if args.external_drivers:
        dir_to_search = args.external_drivers
        extension_to_search = ".sln"
        driver_sln_files = find_sln_file(dir_to_search)
        print_conditionally("Found " + str(len(driver_sln_files)) + " drivers")
        for ql_file in ql_tests:
            ql_tests[ql_file].set_external_drivers(driver_sln_files)
    
    if args.more_verbose:
        no_output = False
   
    if args.existing_database:
        if not os.path.exists(args.existing_database):
            print("Database path does not exist")
            exit(1)
        # TODO doesn't work with --external_drivers

    if args.individual_test:
        ql_files_keys = [x for x in ql_tests if args.individual_test in x.split("\\")[-1]]
        if not ql_files_keys:
            print("Invalid test name: " + args.individual_test + " not found") 
            exit(1)
    elif len(sys.argv) == 1:
        ql_files_keys = [x for x in ql_tests]
    else:
        ql_files_keys = [x for x in ql_tests]
   
    ql_tests = {x:ql_tests[x] for x in ql_tests if x in ql_files_keys}

  
    if ql_tests == []:
        print("Invalid argument")
        exit(1)
    
    if(args.external_drivers):
        run_tests_external_drivers(ql_tests)
    else:
        run_tests(ql_tests)

    end_time = time.time()
    print_conditionally("Total run time: " + str((end_time - start_time)/60) + " minutes")
  