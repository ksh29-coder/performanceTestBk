import os
import time
import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import anthropic
import boto3
from concurrent.futures import ThreadPoolExecutor
from config import *

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PerformanceTest:
    def __init__(self):
        self.anthropic_client = anthropic.AsyncAnthropic(
            api_key=os.getenv('ANTHROPIC_API_KEY')
        )
        
        self.bedrock_client = None
        if TEST_PROVIDER == "bedrock":
            session = boto3.Session(profile_name = 'bedrock')
            self.bedrock_client = session.client(
                service_name='bedrock-runtime',
                region_name='us-east-1')

            
        
        # Create output directories
        Path(OUTPUT_DIR).mkdir(exist_ok=True)
        Path(CHART_OUTPUT_DIR).mkdir(exist_ok=True)
        
        self.results = []

    async def test_anthropic_api(self, prompt, max_tokens=None):
        start_time = time.time()
        try:
            response = await self.anthropic_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=max_tokens or 1000,
                messages=[{"role": "user", "content": prompt}]
            )
            end_time = time.time()
            input_tokens = getattr(response.usage, 'input_tokens', None)
            output_tokens = getattr(response.usage, 'output_tokens', None)
            logger.info(f"Input tokens: {input_tokens}, Output tokens: {output_tokens}")
            return {
                'success': True,
                'latency': end_time - start_time,
                'response': response.content[0].text,
                'provider': 'Anthropic',
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'model': ANTHROPIC_MODEL
            }
        except Exception as e:
            logger.error(f"Anthropic API error: {str(e)}")
            return {
                'success': False,
                'latency': time.time() - start_time,
                'error': str(e),
                'provider': 'Anthropic',
                'input_tokens': None,
                'output_tokens': None,
                'model': ANTHROPIC_MODEL
            }

    async def test_bedrock_api(self, prompt):
        start_time = time.time()
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            })
            
            response = self.bedrock_client.invoke_model(
                modelId=BEDROCK_MODEL_ARN,
                body=body
            )
            
            response_body = json.loads(response['body'].read())
            end_time = time.time()
            
            return {
                'success': True,
                'latency': end_time - start_time,
                'response': response_body['content'][0]['text'],
                'provider': 'Bedrock'
            }
        except Exception as e:
            logger.error(f"Bedrock API error: {str(e)}")
            return {
                'success': False,
                'latency': time.time() - start_time,
                'error': str(e),
                'provider': 'Bedrock'
            }

    async def run_concurrent_tests(self, scenario):
        tasks = []
        for _ in range(CONCURRENT_REQUESTS):
            if TEST_PROVIDER == "anthropic":
                max_tokens = scenario.get('max_tokens', None)
                tasks.append(self.test_anthropic_api(scenario['prompt'], max_tokens=max_tokens))
            elif TEST_PROVIDER == "bedrock":
                tasks.append(self.test_bedrock_api(scenario['prompt']))
        results = await asyncio.gather(*tasks)
        return results

    def analyze_results(self, scenario_results, scenario_name):
        df = pd.DataFrame(scenario_results)
        
        # Calculate statistics
        stats = df.groupby('provider').agg({
            'latency': ['mean', 'std', 'min', 'max'],
            'success': 'mean'
        }).round(3)
        
        # Plot results
        plt.figure(figsize=(10, 6))
        df.boxplot(column='latency', by='provider')
        plt.title(f'Response Time Distribution - {scenario_name}')
        plt.ylabel('Latency (seconds)')
        plt.savefig(f'{CHART_OUTPUT_DIR}/{scenario_name}_boxplot.png')
        plt.close()
        
        return stats

    def plot_all_scenarios_one_chart(self, all_scenario_results):
        """
        Plots a boxplot of latencies for all scenarios in one chart.
        all_scenario_results: list of tuples (scenario_name, results_list)
        """
        data = []
        scenario_names = []
        for scenario_name, results in all_scenario_results:
            latencies = [r['latency'] for r in results if 'latency' in r]
            if latencies:
                data.append(latencies)
                scenario_names.append(scenario_name)
        plt.figure(figsize=(max(10, len(scenario_names)*1.5), 6))
        plt.boxplot(data, labels=scenario_names, showmeans=True)
        plt.title('Latency Distribution for All Scenarios (One Round)')
        plt.ylabel('Latency (seconds)')
        plt.xlabel('Scenario')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(f'{CHART_OUTPUT_DIR}/all_scenarios_boxplot.png')
        plt.close()

    def run_tests(self):
        summary_rows = []
        all_scenario_results = []  # Collect results for all scenarios
        for scenario in TEST_SCENARIOS:
            logger.info(f"Running scenario: {scenario['name']}")
            all_results = []
            for iteration in range(NUM_ITERATIONS):
                logger.info(f"Iteration {iteration + 1}/{NUM_ITERATIONS}")
                # Run concurrent tests
                results = asyncio.run(self.run_concurrent_tests(scenario))
                all_results.extend(results)
            all_scenario_results.append((scenario['name'], all_results))
            
            # Analyze and save results
            stats = self.analyze_results(all_results, scenario['name'])
            logger.info(f"\nResults for {scenario['name']}:\n{stats}")

            # Calculate additional statistics
            latencies = [r['latency'] for r in all_results if 'latency' in r]
            min_duration = round(min(latencies), 3) if latencies else None
            max_duration = round(max(latencies), 3) if latencies else None
            average_duration = round(sum(latencies) / len(latencies), 3) if latencies else None
            num_runs = len(latencies)

            # Prepare summary row (use first successful result, or first result if all failed)
            result_row = next((r for r in all_results if r['success']), all_results[0] if all_results else None)
            if result_row:
                summary_rows.append({
                    'test_name': scenario['name'],
                    'model': result_row.get('model', ''),
                    'input_tokens': result_row.get('input_tokens', ''),
                    'output_tokens': result_row.get('output_tokens', ''),
                    'latency': round(result_row.get('latency', 0), 3),
                    'success': 'success' if result_row.get('success') else 'failed',
                    'min_duration': min_duration,
                    'max_duration': max_duration,
                    'average_duration': average_duration,
                    'num_runs': num_runs
                })

        # Save summary CSV
        if summary_rows:
            summary_df = pd.DataFrame(summary_rows)
            provider = TEST_PROVIDER
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            summary_filename = f"{OUTPUT_DIR}/summary_results_{provider}_{timestamp}.csv"
            summary_df.to_csv(summary_filename, index=False)
            # Plot all scenarios in one chart
            self.plot_all_scenarios_one_chart(all_scenario_results)

def main():
    logger.info("Starting performance tests...")
    test = PerformanceTest()
    test.run_tests()
    logger.info("Performance tests completed!")

if __name__ == "__main__":
    main() 