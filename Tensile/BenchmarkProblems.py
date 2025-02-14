################################################################################
# Copyright 2016-2021 Advanced Micro Devices, Inc. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell cop-
# ies of the Software, and to permit persons to whom the Software is furnished
# to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IM-
# PLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNE-
# CTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
################################################################################

import os
import shutil
import sys
import time

from copy import deepcopy

from . import ClientExecutable
from . import SolutionLibrary
from . import LibraryIO
from . import Utils
from .BenchmarkStructs import BenchmarkProcess, checkParametersAreValid, constructForkPermutations
from .ClientWriter import runClient, writeClientConfig
from .Common import globalParameters, HR, pushWorkingPath, popWorkingPath, print1, print2, \
        printExit, printWarning, ensurePath, startTime, validParameters
from .KernelWriterAssembly import KernelWriterAssembly
from .KernelWriterSource import KernelWriterSource
from .SolutionStructs import Solution, ProblemType, ProblemSizes
from .SolutionWriter import SolutionWriter
from .TensileCreateLibrary import copyStaticFiles, writeSolutionsAndKernels
from .CustomKernels import getCustomKernelConfig


def generateForkedSolutions(problemType, constantParams, forkPermutations):
    """Creates a list with a Solution object for each parameter combination in forkPermutations"""
    print1("# Enumerating Solutions")

    solutions = []
    solutionSet = set()
    for perm in forkPermutations:
        solution = {"ProblemType": deepcopy(problemType.state)}
        solution.update(constantParams)
        solution.update(perm)

        # TODO check if solution matches problem size for exact tile kernels
        solutionObject = Solution(solution)
        if solutionObject["Valid"]:
            if solutionObject not in solutionSet:
                solutionSet.add(solutionObject)
                solutions.append(solutionObject)
        elif globalParameters["PrintSolutionRejectionReason"]:
            print1("rejecting solution " + str(solutionObject))

    return solutions

def getCustomKernelSolutionObj(kernelName, directory=globalParameters["CustomKernelDirectory"]):
    """Creates the Solution object for a custom kernel"""
    kernelConfig = getCustomKernelConfig(kernelName, directory)
    checkParametersAreValid({p: [kernelConfig[p]] for p in kernelConfig \
            if p != "ProblemType"}, validParameters)
    kernelConfig["KernelLanguage"] = "Assembly"
    kernelConfig["CustomKernelName"] = kernelName

    return Solution(kernelConfig)

def generateCustomKernelSolutions(problemType, customKernels, failOnMismatch):
    """Creates a list with a Solution object for each name in customKernel"""
    solutions = []
    for kernelName in customKernels:
        print1("# Processing custom kernel {}".format(kernelName))
        solution = getCustomKernelSolutionObj(kernelName)
        if solution["ProblemType"] != problemType:
            # Raise error if this kernel was specifically requested and problem type doesn't match
            if failOnMismatch:
                benchmarkSet = set([(k,tuple(v)) if type(v) is list else (k,v) \
                        for k,v in problemType.items()])
                customSet = set([(k,tuple(v)) if type(v) is list else (k,v) \
                        for k,v in solution["ProblemType"].items()])

                msg = "The problem type in the config file does not match " \
                        "that of the custom kernel, {}.".format(kernelName) \
                        + "\nDiffering parameters:\n" \
                        + "\tConfig values:\n\t" \
                        + str(sorted(benchmarkSet - (customSet & benchmarkSet))) \
                        + "\n\tCustom kernel values:\n\t" \
                        +  str(sorted(customSet - (customSet & benchmarkSet)))
                printExit(msg)
            else:
                print1("# Rejected {}: Problem Type doesn't match".format(kernelName))
        else:
            print1("# Added {} to solutions".format(kernelName))
            if solution["Valid"]:
                solutions.append(solution)
            elif globalParameters["PrintSolutionRejectionReason"]:
                print1("rejecting solution " + str(solution))

    return solutions

def writeBenchmarkFiles(stepBaseDir, solutions, problemSizes, \
        stepName, solutionSummationSizes):
    """Write all the files needed for a given benchmarking step"""
    if not globalParameters["MergeFiles"]:
        ensurePath(os.path.join(globalParameters["WorkingPath"], "Solutions"))
        ensurePath(os.path.join(globalParameters["WorkingPath"], "Kernels"))

    copyStaticFiles()

    kernels           = []
    kernelHelperOjbs  = []
    kernelNames       = set()
    kernelHelperNames = set()

    # get unique kernels and kernel helpers
    for solution in Utils.tqdm(solutions, "Finding unique solutions"):
        solutionKernels = solution.getKernels()
        for kernel in solutionKernels:
            kName = Solution.getNameFull(kernel)
            if kName not in kernelNames:
                kernels.append(kernel)
                kernelNames.add(kName)

        solutionHelperKernels = solution.getHelperKernelObjects()
        for ko in solutionHelperKernels:
            kname = ko.getKernelName()
            if kname not in kernelHelperNames:
                kernelHelperOjbs.append(ko)
                kernelHelperNames.add(kname)

    solutionSerialNaming = Solution.getSerialNaming(solutions)
    kernelSerialNaming   = Solution.getSerialNaming(kernels)
    solutionMinNaming    = Solution.getMinNaming(solutions)
    kernelMinNaming      = Solution.getMinNaming(kernels)
    solutionWriter       = SolutionWriter(solutionMinNaming, \
            solutionSerialNaming, kernelMinNaming, kernelSerialNaming)
    kernelWriterSource   = KernelWriterSource(kernelMinNaming, kernelSerialNaming)
    kernelWriterAssembly = KernelWriterAssembly(kernelMinNaming, kernelSerialNaming)

    # write solution, kernels and CMake
    problemType = solutions[0]["ProblemType"]
    codeObjectFiles = writeSolutionsAndKernels( \
            globalParameters["WorkingPath"], globalParameters["CxxCompiler"], \
            [problemType], solutions, kernels, kernelHelperOjbs, solutionWriter, \
            kernelWriterSource, kernelWriterAssembly, errorTolerant=True )
    # ^ this is where solutions is mutated

    newLibraryDir = ensurePath(os.path.join(globalParameters["WorkingPath"], 'library'))
    newLibraryFile = os.path.join(newLibraryDir, "TensileLibrary")
    newLibrary = SolutionLibrary.MasterSolutionLibrary.BenchmarkingLibrary(solutions)
    newLibrary.applyNaming(kernelMinNaming)
    LibraryIO.write(newLibraryFile, Utils.state(newLibrary), globalParameters["LibraryFormat"])

    codeObjectFiles = [os.path.relpath(f, globalParameters["WorkingPath"]) \
            for f in codeObjectFiles]

    if "TileAwareSelection" in problemType and problemType["TileAwareSelection"]:
        maxMacroTile0 = 0
        maxMacroTile1 = 0
        for solution in solutions:
            macroTile0 = solution["MacroTile0"]
            macroTile1 = solution["MacroTile1"]
            if macroTile0 > maxMacroTile0:
                maxMacroTile0 = macroTile0
            if macroTile1 > maxMacroTile1:
                maxMacroTile1 = macroTile1
        idealM = 36 * maxMacroTile0
        idealN = 36 * maxMacroTile1
        idealSizes = []
        if problemType["Batched"]:
                for idealK in solutionSummationSizes:
                    idealSize = {"Exact": [idealM, idealN, 1, idealK]}
                    idealSizes.append(idealSize)
        else:
                for idealK in solutionSummationSizes:
                    idealSize = {"Exact": [idealM, idealN, idealK]}
                    idealSizes.append(idealSize)
        idealProblemSizes = ProblemSizes(problemType, idealSizes)
        writeClientConfig(True, solutions, idealProblemSizes, stepName, stepBaseDir, \
            newLibrary, codeObjectFiles, True)
    else:
        writeClientConfig(True, solutions, problemSizes, stepName, stepBaseDir, \
            newLibrary, codeObjectFiles, False)

    if len(solutions) == 0:
        printExit("write solutions and kernels results 0 valid soultion.")

def benchmarkProblemType(problemTypeConfig, problemSizeGroupConfig, problemSizeGroupIdx):
    """Run the benchmarking for a single entry in the BenchmarkProblems of a Tensile config"""
    benchmarkTestFails = 0

    print1("")
    print1(HR)
    print1("# Converting Config to BenchmarkProcess Object")
    print1(HR)
    print1("")
    benchmarkProcess = BenchmarkProcess(problemTypeConfig, problemSizeGroupConfig)

    enableTileSelection = benchmarkProcess.problemType["TileAwareSelection"]
    groupName = "{}_{:02d}".format(str(benchmarkProcess.problemType), problemSizeGroupIdx)
    pushWorkingPath(groupName)
    ensurePath(os.path.join(globalParameters["WorkingPath"], "Data"))

    totalBenchmarkSteps = len(benchmarkProcess)
    resultsFileBaseFinal = None

    print1("# NumBenchmarkSteps: {}".format(totalBenchmarkSteps))
    print1("")
    print1(HR)
    print1("# Done Creating BenchmarkProcess Object")
    print1(HR)

    for benchmarkStepIdx in range(0, totalBenchmarkSteps):
        benchmarkStep = benchmarkProcess[benchmarkStepIdx]
        stepName = str(benchmarkStep)
        shortName = stepName

        print1("\n")
        print1(HR)
        currentTime = time.time()
        elapsedTime = currentTime - startTime
        print1("# Benchmark Step: {} - {} {:.3f}s".format(groupName, stepName, elapsedTime))
        print1("# Num Sizes: {}".format(benchmarkStep.problemSizes.totalProblemSizes))
        print1("# Fork Parameters:")
        for k, v in benchmarkStep.forkParams.items():
            print1("#     {}: {}".format(k, v))

        pushWorkingPath(shortName)
        stepBaseDir = globalParameters["WorkingPath"]
        pushWorkingPath("source")

        # enumerate benchmark permutations and create resulting solution objects
        forkPermutations = constructForkPermutations(benchmarkStep.forkParams)
        maxPossibleSolutions = len(forkPermutations)

        regSolutions = generateForkedSolutions(benchmarkProcess.problemType, \
                benchmarkStep.constantParams, forkPermutations)
        kcSolutions = generateCustomKernelSolutions(benchmarkProcess.problemType, \
                benchmarkStep.customKernels, not benchmarkStep.customKernelWildcard)

        maxPossibleSolutions += len(kcSolutions)
        solutions = regSolutions + kcSolutions

        print1("# Actual Solutions: {} / {} after SolutionStructs\n" \
            .format(len(solutions), maxPossibleSolutions))

        # handle no valid solutions
        if len(solutions) == 0:
            msg = "Your parameters resulted in 0 valid solutions."
            if globalParameters["PrintSolutionRejectionReason"]:
                msg += "\nExamine reject and backtrace messages above to see why" \
                        "and where solutions were rejected."
            else:
                msg += "\nYou should re-run with \"PrintSolutionRejectionReason: True\"" \
                        "to see why each parameter combination was rejected."
            printExit(msg)

        if globalParameters["PrintLevel"] >= 1:
            for solution in solutions:
                print2("#    ({}:{}) {}".format(0, 0, Solution.getNameFull(solution)) )
            print2(HR)

        # write benchmarkFiles
        prevCount = len(solutions)
        writeBenchmarkFiles(stepBaseDir, solutions, benchmarkStep.problemSizes, \
                shortName, [])
        # ^ this mutates solutions

        print1("# Actual Solutions: {} / {} after KernelWriter\n" \
                .format(len(solutions), prevCount ))

        popWorkingPath() # source

        # run benchmarking client
        resultsFileBase = os.path.normpath(os.path.join( \
                globalParameters["WorkingPath"], "../Data", shortName))
        if benchmarkStep.isFinal():
            resultsFileBaseFinal = resultsFileBase
        resultsFileName = resultsFileBase + ".csv"
        solutionsFileName = resultsFileBase + ".yaml"

        if not os.path.exists(resultsFileName) or globalParameters["ForceRedoBenchmarkProblems"]:
            libraryLogicPath = None
            forBenchmark = True
            returncode = runClient(libraryLogicPath, forBenchmark, enableTileSelection)

            if returncode:
                benchmarkTestFails += 1
                printWarning("BenchmarkProblems: Benchmark Process exited with code {}" \
                        .format(returncode))
        else:
            print1("# Already benchmarked; skipping.")

        # write solutions YAML
        LibraryIO.writeSolutions(solutionsFileName, benchmarkStep.problemSizes, solutions)

        # End Iteration
        popWorkingPath() # stepName
        currentTime = time.time()
        elapsedTime = currentTime - startTime
        print1("{}\n# {}\n# {}: End - {:.3f}s\n{}\n" \
                .format(HR, groupName, shortName, elapsedTime, HR))

    popWorkingPath() # ProblemType
    return (resultsFileBaseFinal, benchmarkTestFails)


def main(config):
    """Entry point for the "BenchmarkProblems" section of a Tensile config yaml"""
    ClientExecutable.getClientExecutable()

    dataPath = os.path.join(globalParameters["WorkingPath"], globalParameters["BenchmarkDataPath"])
    pushWorkingPath(globalParameters["BenchmarkProblemsPath"])
    ensurePath(dataPath)

    totalTestFails = 0
    for benchmarkProblemTypeConfig in config:
        problemTypeConfig = benchmarkProblemTypeConfig[0]
        if len(benchmarkProblemTypeConfig) < 2:
            problemSizeGroupConfigs = [{}]
        else:
            problemSizeGroupConfigs = benchmarkProblemTypeConfig[1:]

        for idx, problemSizeGroupConfig in enumerate(problemSizeGroupConfigs):
            print2("ProblemTypeConfig: {}".format(problemTypeConfig))
            problemTypeObj = ProblemType(problemTypeConfig)
            globalParameters["EnableHalf"] = problemTypeObj["DataType"].isHalf()

            # using a suffix to check the csv version (for later addFromCSV())
            csvSuffix = "_CSVWinner" if globalParameters["CSVExportWinner"] else ""
            # results files will be named
            newResultsFileName = os.path.join(dataPath, "{}_{:02d}{}.csv" \
                    .format(str(problemTypeObj), idx, csvSuffix) )
            newSolutionsFileName = os.path.join(dataPath, "{}_{:02d}{}.yaml" \
                    .format(str(problemTypeObj), idx, csvSuffix) )
            newGranularityFileName = os.path.join(dataPath, "{}_{:02d}{}.gsp" \
                    .format(str(problemTypeObj), idx, csvSuffix) )

            # skip if possible
            if globalParameters["ForceRedoBenchmarkProblems"] \
                    or not os.path.exists(newResultsFileName):

                # benchmark problem size group
                (resultsFileBaseFinal, benchmarkErrors) = \
                        benchmarkProblemType(problemTypeConfig, problemSizeGroupConfig, idx)
                totalTestFails += benchmarkErrors

                print("clientExit={} {} for {}" \
                        .format(totalTestFails, "(ERROR)" if totalTestFails else "(PASS)", \
                        globalParameters["ConfigPath"]) )

                # copy data
                resultsFileBase     = resultsFileBaseFinal
                resultsFileName     = resultsFileBase + ".csv"
                solutionsFileName   = resultsFileBase + ".yaml"
                granularityFileName = resultsFileBase + "_Granularity.csv"
                shutil.copy( resultsFileName, newResultsFileName )
                shutil.copy( solutionsFileName, newSolutionsFileName )
                if os.path.isfile(granularityFileName):
                    shutil.copy( granularityFileName, newGranularityFileName )
            else:
                print1("# {}_{:02d} already benchmarked; skipping." \
                        .format(str(problemTypeObj), idx) )

    popWorkingPath()

    if globalParameters["ExitOnFails"] and totalTestFails:
        sys.exit(1)
